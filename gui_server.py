import os
import sys
import json
import asyncio
import threading
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, BackgroundTasks, Query
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Ensure the project directory is on sys.path
KAI_DIR = Path(__file__).resolve().parent
if str(KAI_DIR) not in sys.path:
    sys.path.insert(0, str(KAI_DIR))

# Auto-approve for GUI executions
os.environ["AUTO_APPROVE"] = "true"

from core.tools import WORK_DIR
from core.connectedness import formatManifestContext
from cag.cag import loadCag

app = FastAPI(title="Kaizen Desktop API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global execution state
state_lock = threading.Lock()
current_job = {
    "status": "idle",       # idle, running, completed, error
    "mode": "",             # full, patch
    "prompt": "",
    "stage": "idle",        # prompt, planning, coding, critic, tester, done
    "error": None,
    "last_summary": "",
    "start_time": 0,
    "elapsed": 0,
}

log_subscribers: List[asyncio.Queue] = []
main_loop: Optional[asyncio.AbstractEventLoop] = None


class OutputBroadcaster:
    """Intercepts sys.stdout and sys.stderr to broadcast to SSE subscribers while keeping console output."""
    def __init__(self, original_stream):
        self.original_stream = original_stream

    def write(self, data: str):
        self.original_stream.write(data)
        self.original_stream.flush()
        if not data:
            return
        # Broadcast to all active SSE queues
        if main_loop and log_subscribers:
            for q in list(log_subscribers):
                try:
                    main_loop.call_soon_threadsafe(q.put_nowait, data)
                except Exception:
                    pass

    def flush(self):
        self.original_stream.flush()

    def isatty(self):
        return getattr(self.original_stream, "isatty", lambda: False)()

    def fileno(self):
        return getattr(self.original_stream, "fileno", lambda: 1)()


# Install broadcaster
sys.stdout = OutputBroadcaster(sys.stdout)
sys.stderr = OutputBroadcaster(sys.stderr)


def update_job_status(status=None, stage=None, error=None, last_summary=None):
    with state_lock:
        if status is not None:
            current_job["status"] = status
        if stage is not None:
            current_job["stage"] = stage
        if error is not None:
            current_job["error"] = error
        if last_summary is not None:
            current_job["last_summary"] = last_summary


def execute_kaizen_pipeline(query: str, force_mode: Optional[str] = None):
    """Executes the Kaizen multi-agent pipeline in a worker thread."""
    try:
        import main as kai_main
        from agents.prompt import PromptAgent
        from agents.planneragent import PlannerAgent
        from agents.patchclassifier import classifyIntent, buildPatchInstruction
        from agents.dag import DAG
        from agents.scheduler import Scheduler
        from agents.hitl import reviewDeliverables

        update_job_status(status="running", stage="analyzing", error=None)
        print(f"\n[Kaizen UI] Received task: {query}\n")

        retrievedMemories = []
        if kai_main.shouldRetrieveMemory(query):
            try:
                mems = kai_main.memoryManager.searchMemory(query, topK=3)
                retrievedMemories = [m["content"] for m in mems]
            except Exception:
                retrievedMemories = []

        mode = force_mode or classifyIntent(query)
        if mode in ("direct", "patch"):
            update_job_status(stage="patching")
            print("\n[Kaizen UI] Direct execution mode, running tool-enabled agent loop.\n")
            loadCag(str(WORK_DIR))
            patchInstruction = buildPatchInstruction(query, WORK_DIR)
            if retrievedMemories:
                memStr = "\n".join(f"- {m}" for m in retrievedMemories)
                patchInstruction = f"{patchInstruction}\n\nRelevant past lessons:\n{memStr}"
            patchResult = kai_main.runCoder(patchInstruction)
            summary = patchResult.get("coderMessage", "").strip() if isinstance(patchResult, dict) else ""
            update_job_status(status="completed", stage="done", last_summary=summary)
            print("\n[Kaizen UI] Patch complete!\n")
        else:
            update_job_status(stage="prompt_analysis")
            print("[Kaizen UI] Analyzing requirements and deliverables...")
            promptAgent = PromptAgent()
            curQuery = query
            if retrievedMemories:
                mStr = "\n".join(f"- {m}" for m in retrievedMemories)
                curQuery = f"{query}\n\nRelevant past memories/lessons:\n{mStr}"

            existingAst = formatManifestContext(WORK_DIR)
            if existingAst and "Workspace is currently empty" not in existingAst:
                curQuery = f"{curQuery}\n\nExisting Workspace Code & Structure:\n{existingAst}"

            promptOutput = promptAgent.process(curQuery)
            deliverables = promptOutput.get("deliverables", [])
            techStack = promptOutput.get("tech_stack") or promptOutput.get("techStack") or ""
            fileStructure = promptOutput.get("file_structure") or promptOutput.get("fileStructure") or []

            update_job_status(stage="dag_planning")
            print("[Kaizen UI] Constructing DAG Milestone Plan...")
            plannerAgent = PlannerAgent()
            dagPlan = plannerAgent.plan(promptOutput)

            dag = DAG()
            for t in dagPlan.taskNodes:
                t.name = getattr(t, "objective", t.id)
                t.agent = "Coding"
                dag.addTask(t)
            dag.build()

            print(f"[Kaizen UI] Generated {len(dagPlan.taskNodes)} task nodes. Order: {dag.topologicalSort()}")

            update_job_status(stage="executing_tasks")
            loadCag(str(WORK_DIR))
            scheduler = Scheduler(
                dag,
                curQuery,
                techStack=techStack,
                fileStructure=fileStructure,
                coderFn=kai_main.runCoder,
                evalFn=kai_main.runBatchEval
            )
            asyncio.run(scheduler.run())

            kai_main.printProjectSummary(query, techStack, scheduler.taskOutputs, WORK_DIR)
            update_job_status(status="completed", stage="done", last_summary=f"Completed {len(dagPlan.taskNodes)} tasks successfully.")
            print("\n[Kaizen UI] All tasks completed and verified!\n")

    except Exception as e:
        import traceback
        traceback.print_exc()
        update_job_status(status="error", stage="error", error=str(e))
        print(f"\n[Kaizen UI Error] {e}\n")


@app.get("/api/status")
async def get_status():
    with state_lock:
        return dict(current_job)


@app.post("/api/run")
async def run_pipeline(payload: Dict[str, Any], background_tasks: BackgroundTasks):
    import time
    with state_lock:
        if current_job["status"] == "running":
            return JSONResponse(status_code=400, content={"error": "A task is already running."})
        prompt = payload.get("prompt", "").strip()
        if not prompt:
            return JSONResponse(status_code=400, content={"error": "Prompt cannot be empty."})
        mode = payload.get("mode", "auto")
        current_job["prompt"] = prompt
        current_job["mode"] = mode
        current_job["status"] = "running"
        current_job["error"] = None
        current_job["start_time"] = time.time()
        current_job["elapsed"] = 0

    background_tasks.add_task(execute_kaizen_pipeline, prompt, None if mode == "auto" else mode)
    return {"status": "started", "prompt": prompt, "mode": mode}


@app.post("/api/stop")
async def stop_pipeline():
    with state_lock:
        if current_job["status"] == "running":
            current_job["status"] = "idle"
            current_job["stage"] = "idle"
            print("\n[Kaizen UI] Execution cancelled by user.\n")
            return {"status": "cancelled"}
    return {"status": "not_running"}


@app.get("/api/dag")
async def get_dag():
    """Returns the generated DAG visualization and task graph."""
    dag_dir = WORK_DIR / "DAG"
    dot_file = dag_dir / "dag_flow.dot"
    mmd_file = dag_dir / "dag_flow.mmd"
    md_file = dag_dir / "dag_flow.md"

    res = {"dot": "", "mermaid": "", "markdown": ""}
    if dot_file.exists():
        res["dot"] = dot_file.read_text(encoding="utf-8", errors="ignore")
    if mmd_file.exists():
        res["mermaid"] = mmd_file.read_text(encoding="utf-8", errors="ignore")
    if md_file.exists():
        res["markdown"] = md_file.read_text(encoding="utf-8", errors="ignore")
    return res


@app.get("/api/config")
async def get_config():
    """Returns the current model and system configuration."""
    return {
        "llm_provider": os.getenv("LLM_PROVIDER", "vertexai"),
        "llm_model": os.getenv("LLM_MODEL", "gemini-2.5-flash"),
        "auto_approve": os.getenv("AUTO_APPROVE", "true").lower() in ("true", "1", "yes"),
        "google_cloud_project": os.getenv("GOOGLE_CLOUD_PROJECT", ""),
        "google_cloud_location": os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
        "has_gemini_key": bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
        "has_openai_key": bool(os.getenv("OPENAI_API_KEY")),
        "has_anthropic_key": bool(os.getenv("ANTHROPIC_API_KEY")),
        "work_dir": str(WORK_DIR),
    }


@app.post("/api/config")
async def update_config(payload: Dict[str, Any]):
    """Updates runtime environment configuration."""
    provider = payload.get("llm_provider")
    if provider:
        os.environ["LLM_PROVIDER"] = str(provider).strip().lower()

    model = payload.get("llm_model")
    if model:
        os.environ["LLM_MODEL"] = str(model).strip()

    if "auto_approve" in payload:
        val = "true" if payload["auto_approve"] else "false"
        os.environ["AUTO_APPROVE"] = val

    project = payload.get("google_cloud_project")
    if project is not None:
        os.environ["GOOGLE_CLOUD_PROJECT"] = str(project).strip()

    location = payload.get("google_cloud_location")
    if location is not None:
        os.environ["GOOGLE_CLOUD_LOCATION"] = str(location).strip()

    gemini_key = payload.get("gemini_api_key")
    if gemini_key:
        os.environ["GEMINI_API_KEY"] = str(gemini_key).strip()

    openai_key = payload.get("openai_api_key")
    if openai_key:
        os.environ["OPENAI_API_KEY"] = str(openai_key).strip()

    anthropic_key = payload.get("anthropic_api_key")
    if anthropic_key:
        os.environ["ANTHROPIC_API_KEY"] = str(anthropic_key).strip()

    # Re-initialize llm and flags in core.config if possible
    try:
        import core.config as cfg
        if "auto_approve" in payload:
            cfg.autoApprove = bool(payload["auto_approve"])
            cfg.AUTO_APPROVE = bool(payload["auto_approve"])
        cfg.llm = cfg.get_llm()
    except Exception:
        pass

    return {"status": "updated", "config": await get_config()}


@app.get("/api/stream")
async def sse_logs():
    """Server-Sent Events endpoint streaming real-time logs to the UI."""
    q: asyncio.Queue = asyncio.Queue()
    log_subscribers.append(q)

    async def event_generator():
        try:
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"
            while True:
                msg = await q.get()
                yield f"data: {json.dumps({'type': 'log', 'text': msg})}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if q in log_subscribers:
                log_subscribers.remove(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )


@app.get("/api/files")
async def list_workspace_files():
    """Returns the list of files in work/ with metadata."""
    if not WORK_DIR.exists():
        return {"files": []}

    skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv"}
    files_list = []
    for f in sorted(WORK_DIR.rglob("*")):
        if f.is_file() and not any(part in skip_dirs or part.startswith(".") for part in f.parts):
            rel = f.relative_to(WORK_DIR).as_posix()
            files_list.append({
                "path": rel,
                "name": f.name,
                "size": f.stat().st_size,
                "suffix": f.suffix.lower()
            })
    return {"files": files_list}


@app.get("/api/file-content")
async def get_file_content(path: str = Query(...)):
    target = (WORK_DIR / path).resolve()
    if not str(target).startswith(str(WORK_DIR.resolve())):
        return JSONResponse(status_code=403, content={"error": "Access denied"})
    if not target.exists() or not target.is_file():
        return JSONResponse(status_code=404, content={"error": "File not found"})

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
        return {"path": path, "content": content}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/launch-project")
async def launch_project():
    """Launches the created project (e.g. work/main.py)."""
    candidates = ["main.py", "app.py", "game.py", "index.html", "container_water.py"]
    chosen = None
    for cand in candidates:
        if (WORK_DIR / cand).exists():
            chosen = WORK_DIR / cand
            break

    if not chosen:
        # Pick first python file
        py_files = list(WORK_DIR.glob("*.py"))
        if py_files:
            chosen = py_files[0]

    if not chosen:
        return JSONResponse(status_code=404, content={"error": "No runnable entrypoint found in work/"})

    if chosen.suffix == ".py":
        python_exe = sys.executable
        subprocess.Popen([python_exe, str(chosen)], cwd=str(WORK_DIR))
        return {"launched": chosen.name, "type": "python"}
    elif chosen.suffix == ".html":
        import webbrowser
        webbrowser.open(str(chosen.resolve()))
        return {"launched": chosen.name, "type": "browser"}

    return {"launched": chosen.name}


@app.post("/api/open-folder")
async def open_workspace_folder():
    """Opens work/ directory in Windows Explorer."""
    if os.name == "nt":
        os.startfile(str(WORK_DIR))
    else:
        subprocess.Popen(["xdg-open", str(WORK_DIR)])
    return {"status": "opened"}


# Mount static files
static_dir = KAI_DIR / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def serve_index():
    index_file = static_dir / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h3>Kaizen UI loading...</h3>")


def launch_native_window(url: str):
    """Opens url in standalone desktop app mode using Edge or Chrome."""
    import time
    time.sleep(1.2)
    edge_paths = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
    ]
    for p in edge_paths:
        if os.path.exists(p):
            try:
                subprocess.Popen([p, f"--app={url}", "--window-size=1280,820"])
                return
            except Exception:
                pass

    chrome_path = os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe")
    if os.path.exists(chrome_path):
        try:
            subprocess.Popen([chrome_path, f"--app={url}", "--window-size=1280,820"])
            return
        except Exception:
            pass

    import webbrowser
    webbrowser.open(url)


if __name__ == "__main__":
    import asyncio
    main_loop = asyncio.new_event_loop()
    threading.Thread(target=main_loop.run_forever, daemon=True).start()

    port = 8765
    server_url = f"http://127.0.0.1:{port}"
    print(f"\n[Kaizen UI] Server launching on {server_url} ...")
    
    # Launch native desktop app window
    threading.Thread(target=launch_native_window, args=(server_url,), daemon=True).start()

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")

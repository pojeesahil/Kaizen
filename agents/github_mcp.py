import os
import subprocess
from pathlib import Path
from typing import Optional
import requests
from mcp.server.mcpserver import MCPServer

mcpServer = MCPServer("kaizen-github-mcp")

def getGitHubToken() -> str:
    tokenVal = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    if not tokenVal:
        envPath = Path(__file__).resolve().parent.parent / "secure.env"
        if envPath.exists():
            try:
                from dotenv import load_dotenv
                load_dotenv(str(envPath))
                tokenVal = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
            except Exception:
                pass
    return tokenVal

def resolveRepoPath(repoPath: str = "") -> Path:
    workFolder = (Path(__file__).resolve().parent.parent / "work").resolve()
    workFolder.mkdir(parents=True, exist_ok=True)
    if repoPath:
        targetPath = Path(repoPath)
        if not targetPath.is_absolute():
            targetPath = (workFolder / targetPath).resolve()
        if str(targetPath).startswith(str(workFolder)) and targetPath.exists():
            return targetPath
    subDirs = [d for d in workFolder.iterdir() if d.is_dir() and (d / ".git").exists()]
    if subDirs:
        return subDirs[0]
    return workFolder

def extractRepoDetails(repoPath: str = "") -> tuple[str, str]:
    resolvedPath = resolveRepoPath(repoPath)
    try:
        procResult = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(resolvedPath),
            capture_output=True,
            text=True
        )
        if procResult.returncode != 0 or not procResult.stdout.strip():
            return "", ""
        remoteURL = procResult.stdout.strip()
        cleanedURL = remoteURL.removesuffix(".git")
        if "github.com/" in cleanedURL:
            urlParts = cleanedURL.split("github.com/")[1].split("/")
            if len(urlParts) >= 2:
                return urlParts[0], urlParts[1]
        elif "github.com:" in cleanedURL:
            urlParts = cleanedURL.split("github.com:")[1].split("/")
            if len(urlParts) >= 2:
                return urlParts[0], urlParts[1]
    except Exception:
        pass
    return "", ""

def getGitHubHeaders() -> dict[str, str]:
    headerDict = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Kaizen-GitHubAgent"
    }
    tokenVal = getGitHubToken()
    if tokenVal:
        headerDict["Authorization"] = f"token {tokenVal}"
    return headerDict

_cachedAuthUser = ""

def getAuthenticatedUser() -> str:
    global _cachedAuthUser
    if _cachedAuthUser:
        return _cachedAuthUser
    try:
        resp = requests.get("https://api.github.com/user", headers=getGitHubHeaders(), timeout=5)
        if resp.status_code == 200:
            _cachedAuthUser = resp.json().get("login", "")
            return _cachedAuthUser
    except Exception:
        pass
    return ""

def resolveRepoTarget(ownerName: str = "", repoName: str = "", repoPath: str = "") -> tuple[str, str]:
    resolvedOwner, resolvedRepo = ownerName, repoName
    autoOwner, autoRepo = extractRepoDetails(repoPath)
    if not resolvedOwner:
        if resolvedRepo and autoRepo and resolvedRepo.lower() != autoRepo.lower():
            resolvedOwner = getAuthenticatedUser() or autoOwner
        else:
            resolvedOwner = autoOwner or getAuthenticatedUser()
    return resolvedOwner, resolvedRepo or autoRepo

@mcpServer.tool()
def getGitStatus(repoPath: str = "") -> dict:
    resolvedPath = resolveRepoPath(repoPath)
    try:
        branchProc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(resolvedPath),
            capture_output=True,
            text=True
        )
        currentBranch = branchProc.stdout.strip() if branchProc.returncode == 0 else "unknown"

        statusProc = subprocess.run(
            ["git", "status", "--short"],
            cwd=str(resolvedPath),
            capture_output=True,
            text=True
        )
        fullStatusProc = subprocess.run(
            ["git", "status"],
            cwd=str(resolvedPath),
            capture_output=True,
            text=True
        )
        return {
            "success": True,
            "branch": currentBranch,
            "shortStatus": statusProc.stdout.strip(),
            "fullStatus": fullStatusProc.stdout.strip(),
            "isClean": len(statusProc.stdout.strip()) == 0
        }
    except Exception as errVal:
        return {"success": False, "error": str(errVal)}

@mcpServer.tool()
def gitAdd(files: Optional[list[str]] = None, repoPath: str = "") -> dict:
    resolvedPath = resolveRepoPath(repoPath)
    targetFiles = files if files else ["."]
    try:
        procResult = subprocess.run(
            ["git", "add"] + targetFiles,
            cwd=str(resolvedPath),
            capture_output=True,
            text=True
        )
        if procResult.returncode == 0:
            return {"success": True, "message": f"Successfully staged: {' '.join(targetFiles)}"}
        return {"success": False, "error": procResult.stderr.strip(), "returnCode": procResult.returncode}
    except Exception as errVal:
        return {"success": False, "error": str(errVal)}

@mcpServer.tool()
def gitCommit(message: str, repoPath: str = "") -> dict:
    resolvedPath = resolveRepoPath(repoPath)
    cleanMessage = message.strip()
    if not cleanMessage:
        return {"success": False, "error": "Commit message cannot be empty."}
    try:
        procResult = subprocess.run(
            ["git", "commit", "-m", cleanMessage],
            cwd=str(resolvedPath),
            capture_output=True,
            text=True
        )
        if procResult.returncode == 0:
            return {"success": True, "message": procResult.stdout.strip()}
        return {"success": False, "error": procResult.stderr.strip() or procResult.stdout.strip(), "returnCode": procResult.returncode}
    except Exception as errVal:
        return {"success": False, "error": str(errVal)}

@mcpServer.tool()
def gitPull(remoteName: str = "origin", branchName: str = "", repoPath: str = "") -> dict:
    resolvedPath = resolveRepoPath(repoPath)
    effectiveBranch = branchName
    if not effectiveBranch:
        branchProc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(resolvedPath),
            capture_output=True,
            text=True
        )
        if branchProc.returncode == 0 and branchProc.stdout.strip():
            effectiveBranch = branchProc.stdout.strip()

    cmdArgs = ["git", "pull", remoteName]
    if effectiveBranch and effectiveBranch != "HEAD":
        cmdArgs.append(effectiveBranch)

    try:
        procResult = subprocess.run(
            cmdArgs,
            cwd=str(resolvedPath),
            capture_output=True,
            text=True
        )
        if procResult.returncode == 0:
            return {"success": True, "message": procResult.stdout.strip() or "Already up to date."}
        return {"success": False, "error": procResult.stderr.strip() or procResult.stdout.strip(), "returnCode": procResult.returncode}
    except Exception as errVal:
        return {"success": False, "error": str(errVal)}

@mcpServer.tool()
def gitPush(remoteName: str = "origin", branchName: str = "", isForce: bool = False, isConfirmed: bool = False, repoPath: str = "") -> dict:
    if isForce and not isConfirmed:
        return {
            "success": False,
            "error": "Force push blocked: Requires explicit confirmation parameter (isConfirmed=True) to prevent remote branch overwrite."
        }
    resolvedPath = resolveRepoPath(repoPath)
    effectiveBranch = branchName
    if not effectiveBranch:
        branchProc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(resolvedPath),
            capture_output=True,
            text=True
        )
        if branchProc.returncode == 0 and branchProc.stdout.strip():
            effectiveBranch = branchProc.stdout.strip()

    cmdArgs = ["git", "push", remoteName]
    if effectiveBranch and effectiveBranch != "HEAD":
        cmdArgs.append(effectiveBranch)
    if isForce:
        cmdArgs.append("--force")
    try:
        procResult = subprocess.run(
            cmdArgs,
            cwd=str(resolvedPath),
            capture_output=True,
            text=True
        )
        if procResult.returncode == 0:
            return {"success": True, "message": procResult.stdout.strip() or procResult.stderr.strip() or "Push complete."}
        return {"success": False, "error": procResult.stderr.strip() or procResult.stdout.strip(), "returnCode": procResult.returncode}
    except Exception as errVal:
        return {"success": False, "error": str(errVal)}


@mcpServer.tool()
def getGitBranches(repoPath: str = "") -> dict:
    resolvedPath = resolveRepoPath(repoPath)
    try:
        procResult = subprocess.run(
            ["git", "branch", "-a"],
            cwd=str(resolvedPath),
            capture_output=True,
            text=True
        )
        if procResult.returncode == 0:
            branchLines = [line.strip() for line in procResult.stdout.strip().splitlines() if line.strip()]
            currentBranch = ""
            for line in branchLines:
                if line.startswith("*"):
                    currentBranch = line.lstrip("* ").strip()
                    break
            return {
                "success": True,
                "currentBranch": currentBranch,
                "branches": branchLines,
                "rawOutput": procResult.stdout.strip()
            }
        return {"success": False, "error": procResult.stderr.strip()}
    except Exception as errVal:
        return {"success": False, "error": str(errVal)}

@mcpServer.tool()
def gitCheckout(branchName: str, createNew: bool = False, repoPath: str = "") -> dict:
    resolvedPath = resolveRepoPath(repoPath)
    cmdArgs = ["git", "checkout", "-b", branchName] if createNew else ["git", "checkout", branchName]
    try:
        procResult = subprocess.run(
            cmdArgs,
            cwd=str(resolvedPath),
            capture_output=True,
            text=True
        )
        if procResult.returncode == 0:
            return {"success": True, "message": procResult.stderr.strip() or procResult.stdout.strip()}
        return {"success": False, "error": procResult.stderr.strip() or procResult.stdout.strip(), "returnCode": procResult.returncode}
    except Exception as errVal:
        return {"success": False, "error": str(errVal)}

@mcpServer.tool()
def getGitLog(maxCount: int = 5, repoPath: str = "") -> dict:
    resolvedPath = resolveRepoPath(repoPath)
    try:
        procResult = subprocess.run(
            ["git", "log", f"-n{maxCount}", "--oneline"],
            cwd=str(resolvedPath),
            capture_output=True,
            text=True
        )
        if procResult.returncode == 0:
            commitList = [line.strip() for line in procResult.stdout.strip().splitlines() if line.strip()]
            return {"success": True, "commits": commitList, "rawOutput": procResult.stdout.strip()}
        return {"success": False, "error": procResult.stderr.strip()}
    except Exception as errVal:
        return {"success": False, "error": str(errVal)}

@mcpServer.tool()
def getGitDiff(stagedOnly: bool = False, repoPath: str = "") -> dict:
    resolvedPath = resolveRepoPath(repoPath)
    cmdArgs = ["git", "diff", "--staged"] if stagedOnly else ["git", "diff"]
    try:
        procResult = subprocess.run(
            cmdArgs,
            cwd=str(resolvedPath),
            capture_output=True,
            text=True
        )
        if procResult.returncode == 0:
            return {
                "success": True,
                "diff": procResult.stdout.strip(),
                "isEmpty": len(procResult.stdout.strip()) == 0
            }
        return {"success": False, "error": procResult.stderr.strip()}
    except Exception as errVal:
        return {"success": False, "error": str(errVal)}

@mcpServer.tool()
def runGitCommand(commandText: str, repoPath: str = "", isConfirmed: bool = False) -> dict:
    resolvedPath = resolveRepoPath(repoPath)
    cleanCmd = commandText.strip()
    if cleanCmd.startswith("git "):
        cleanCmd = cleanCmd[4:].strip()

    destructiveKeywords = ["reset --hard", "clean -f", "clean -fd", "push --force", "push -f", "branch -D"]
    for kw in destructiveKeywords:
        if kw in cleanCmd and not isConfirmed:
            return {
                "success": False,
                "error": f"Destructive command '{cleanCmd}' was blocked for safety. Set isConfirmed=True to execute."
            }

    import shlex
    try:
        cmdParts = shlex.split(cleanCmd)
    except Exception:
        cmdParts = cleanCmd.split()

    try:
        procResult = subprocess.run(
            ["git"] + cmdParts,
            cwd=str(resolvedPath),
            capture_output=True,
            text=True
        )
        return {
            "success": procResult.returncode == 0,
            "stdout": procResult.stdout.strip(),
            "stderr": procResult.stderr.strip(),
            "returnCode": procResult.returncode
        }
    except Exception as errVal:
        return {"success": False, "error": str(errVal)}


@mcpServer.tool()
def getRepositoryInfo(ownerName: str = "", repoName: str = "", repoPath: str = "") -> dict:
    resolvedOwner, resolvedRepo = resolveRepoTarget(ownerName, repoName, repoPath)

    if not resolvedOwner or not resolvedRepo:
        return {"success": False, "error": "Repository owner and name not provided and could not be detected from git remote."}

    apiURL = f"https://api.github.com/repos/{resolvedOwner}/{resolvedRepo}"
    try:
        HTTPresponse = requests.get(apiURL, headers=getGitHubHeaders(), timeout=10)
        if HTTPresponse.status_code == 200:
            data = HTTPresponse.json()
            return {
                "success": True,
                "name": data.get("name", ""),
                "fullName": data.get("full_name", ""),
                "description": data.get("description", ""),
                "stars": data.get("stargazers_count", 0),
                "forks": data.get("forks_count", 0),
                "openIssues": data.get("open_issues_count", 0),
                "defaultBranch": data.get("default_branch", "main"),
                "isPrivate": data.get("private", False),
                "htmlURL": data.get("html_url", "")
            }
        return {"success": False, "error": f"GitHub API error {HTTPresponse.status_code}: {HTTPresponse.text}"}
    except Exception as errVal:
        return {"success": False, "error": str(errVal)}

@mcpServer.tool()
def getIssues(ownerName: str = "", repoName: str = "", issueState: str = "open", maxCount: int = 10, repoPath: str = "") -> dict:
    resolvedOwner, resolvedRepo = resolveRepoTarget(ownerName, repoName, repoPath)

    if not resolvedOwner or not resolvedRepo:
        return {"success": False, "error": "Repository owner and name not provided and could not be detected from git remote."}

    apiURL = f"https://api.github.com/repos/{resolvedOwner}/{resolvedRepo}/issues"
    reqQuery = {"state": issueState, "per_page": maxCount}
    try:
        HTTPresponse = requests.get(apiURL, headers=getGitHubHeaders(), params=reqQuery, timeout=10)
        if HTTPresponse.status_code == 200:
            rawIssues = HTTPresponse.json()
            issueList = []
            for item in rawIssues:
                if "pull_request" not in item:
                    issueList.append({
                        "number": item.get("number"),
                        "title": item.get("title", ""),
                        "state": item.get("state", ""),
                        "user": item.get("user", {}).get("login", ""),
                        "htmlURL": item.get("html_url", ""),
                        "body": (item.get("body") or "")[:200]
                    })
            return {"success": True, "count": len(issueList), "issues": issueList}
        return {"success": False, "error": f"GitHub API error {HTTPresponse.status_code}: {HTTPresponse.text}"}
    except Exception as errVal:
        return {"success": False, "error": str(errVal)}

@mcpServer.tool()
def createIssue(titleText: str, bodyText: str = "", ownerName: str = "", repoName: str = "", repoPath: str = "") -> dict:
    tokenVal = getGitHubToken()
    if not tokenVal:
        return {"success": False, "error": "GITHUB_TOKEN or GH_TOKEN environment variable is required to create issues."}

    resolvedOwner, resolvedRepo = resolveRepoTarget(ownerName, repoName, repoPath)

    if not resolvedOwner or not resolvedRepo:
        return {"success": False, "error": "Repository owner and name not provided and could not be detected from git remote."}

    apiURL = f"https://api.github.com/repos/{resolvedOwner}/{resolvedRepo}/issues"
    payload = {"title": titleText, "body": bodyText}
    try:
        HTTPresponse = requests.post(apiURL, headers=getGitHubHeaders(), json=payload, timeout=10)
        if HTTPresponse.status_code == 201:
            data = HTTPresponse.json()
            return {
                "success": True,
                "issueNumber": data.get("number"),
                "htmlURL": data.get("html_url", ""),
                "title": data.get("title", "")
            }
        return {"success": False, "error": f"GitHub API error {HTTPresponse.status_code}: {HTTPresponse.text}"}
    except Exception as errVal:
        return {"success": False, "error": str(errVal)}

@mcpServer.tool()
def commentOnIssue(issueNumber: int, commentText: str, ownerName: str = "", repoName: str = "", repoPath: str = "") -> dict:
    tokenVal = getGitHubToken()
    if not tokenVal:
        return {"success": False, "error": "GITHUB_TOKEN or GH_TOKEN environment variable is required to post comments."}

    resolvedOwner, resolvedRepo = resolveRepoTarget(ownerName, repoName, repoPath)

    if not resolvedOwner or not resolvedRepo:
        return {"success": False, "error": "Repository owner and name not provided and could not be detected from git remote."}

    apiURL = f"https://api.github.com/repos/{resolvedOwner}/{resolvedRepo}/issues/{issueNumber}/comments"
    payload = {"body": commentText}
    try:
        HTTPresponse = requests.post(apiURL, headers=getGitHubHeaders(), json=payload, timeout=10)
        if HTTPresponse.status_code == 201:
            data = HTTPresponse.json()
            return {
                "success": True,
                "commentId": data.get("id"),
                "htmlURL": data.get("html_url", ""),
                "message": f"Successfully commented on issue #{issueNumber}"
            }
        return {"success": False, "error": f"GitHub API error {HTTPresponse.status_code}: {HTTPresponse.text}"}
    except Exception as errVal:
        return {"success": False, "error": str(errVal)}

@mcpServer.tool()
def getPullRequests(ownerName: str = "", repoName: str = "", prState: str = "open", maxCount: int = 10, repoPath: str = "") -> dict:
    resolvedOwner, resolvedRepo = resolveRepoTarget(ownerName, repoName, repoPath)

    if not resolvedOwner or not resolvedRepo:
        return {"success": False, "error": "Repository owner and name not provided and could not be detected from git remote."}

    apiURL = f"https://api.github.com/repos/{resolvedOwner}/{resolvedRepo}/pulls"
    reqQuery = {"state": prState, "per_page": maxCount}
    try:
        HTTPresponse = requests.get(apiURL, headers=getGitHubHeaders(), params=reqQuery, timeout=10)
        if HTTPresponse.status_code == 200:
            rawPRs = HTTPresponse.json()
            prList = []
            for item in rawPRs:
                prList.append({
                    "number": item.get("number"),
                    "title": item.get("title", ""),
                    "state": item.get("state", ""),
                    "user": item.get("user", {}).get("login", ""),
                    "headBranch": item.get("head", {}).get("ref", ""),
                    "baseBranch": item.get("base", {}).get("ref", ""),
                    "htmlURL": item.get("html_url", "")
                })
            return {"success": True, "count": len(prList), "pullRequests": prList}
        return {"success": False, "error": f"GitHub API error {HTTPresponse.status_code}: {HTTPresponse.text}"}
    except Exception as errVal:
        return {"success": False, "error": str(errVal)}

@mcpServer.tool()
def createPullRequest(titleText: str, headBranch: str, baseBranch: str = "main", bodyText: str = "", ownerName: str = "", repoName: str = "", repoPath: str = "") -> dict:
    tokenVal = getGitHubToken()
    if not tokenVal:
        return {"success": False, "error": "GITHUB_TOKEN or GH_TOKEN environment variable is required to create pull requests."}

    resolvedOwner, resolvedRepo = resolveRepoTarget(ownerName, repoName, repoPath)

    if not resolvedOwner or not resolvedRepo:
        return {"success": False, "error": "Repository owner and name not provided and could not be detected from git remote."}

    apiURL = f"https://api.github.com/repos/{resolvedOwner}/{resolvedRepo}/pulls"
    payload = {
        "title": titleText,
        "head": headBranch,
        "base": baseBranch,
        "body": bodyText
    }
    try:
        HTTPresponse = requests.post(apiURL, headers=getGitHubHeaders(), json=payload, timeout=10)
        if HTTPresponse.status_code == 201:
            data = HTTPresponse.json()
            return {
                "success": True,
                "prNumber": data.get("number"),
                "htmlURL": data.get("html_url", ""),
                "title": data.get("title", "")
            }
        return {"success": False, "error": f"GitHub API error {HTTPresponse.status_code}: {HTTPresponse.text}"}
    except Exception as errVal:
        return {"success": False, "error": str(errVal)}

@mcpServer.tool()
def commentOnPullRequest(prNumber: int, commentText: str, ownerName: str = "", repoName: str = "", repoPath: str = "") -> dict:
    return commentOnIssue(issueNumber=prNumber, commentText=commentText, ownerName=ownerName, repoName=repoName, repoPath=repoPath)

def runMCPserver() -> None:
    mcpServer.run(transport="stdio")

if __name__ == "__main__":
    runMCPserver()

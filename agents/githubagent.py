import os
import json
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

class GitHubAgent:

    def __init__(self, workDir: Path):
        self.workDir = workDir
        self.token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""

    def runGitCommand(self, args: list[str]) -> tuple[int, str, str]:
        proc = subprocess.run(
            ["git"] + args,
            cwd=str(self.workDir.resolve()),
            capture_output=True,
            text=True
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()

    def parseIssueUrl(self, text: str) -> tuple[str, str, str]:
        trimmed = text.strip()
        marker = "github.com/"
        if marker not in trimmed:
            return "", "", ""
        afterMarker = trimmed.split(marker, 1)[1]
        parts = afterMarker.split("/")
        if len(parts) >= 4 and parts[2] == "issues":
            ownerName = parts[0]
            repoName = parts[1]
            issueNum = parts[3].split("#")[0].split("?")[0]
            if issueNum.isdigit():
                return ownerName, repoName, issueNum
        return "", "", ""

    def fetchIssue(self, ownerName: str, repoName: str, issueNum: str) -> dict:
        apiUrl = f"https://api.github.com/repos/{ownerName}/{repoName}/issues/{issueNum}"
        headers = {
            "User-Agent": "Kai-GitHubAgent",
            "Accept": "application/vnd.github.v3+json"
        }
        if self.token:
            headers["Authorization"] = f"token {self.token}"
        try:
            req = urllib.request.Request(apiUrl, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return {
                    "title": data.get("title", ""),
                    "body": data.get("body", "") or "",
                    "number": issueNum,
                    "owner": ownerName,
                    "repo": repoName
                }
        except Exception:
            return {}

    def ensureGitignore(self) -> None:
        ignorePath = self.workDir / ".gitignore"
        ignoreEntries = [
            "node_modules/",
            "__pycache__/",
            ".venv/",
            "venv/",
            "dist/",
            "build/",
            ".next/",
            ".nuxt/",
            ".cache/",
            "coverage/",
            "*.log",
            ".DS_Store"
        ]
        existing = ""
        if ignorePath.exists():
            try:
                with open(ignorePath, "r", encoding="utf-8") as f:
                    existing = f.read()
            except Exception:
                existing = ""
        newLines = []
        for entry in ignoreEntries:
            if entry not in existing:
                newLines.append(entry)
        if newLines:
            prefix = "\n" if existing and not existing.endswith("\n") else ""
            with open(ignorePath, "a", encoding="utf-8") as f:
                f.write(prefix + "\n".join(newLines) + "\n")

    def ensureRepo(self) -> bool:
        self.workDir.mkdir(parents=True, exist_ok=True)
        gitDir = self.workDir / ".git"
        if not gitDir.exists():
            code, _, _ = self.runGitCommand(["init"])
            if code != 0:
                return False
        self.ensureGitignore()
        return True

    def getCurrentBranch(self) -> str:
        code, out, _ = self.runGitCommand(["rev-parse", "--abbrev-ref", "HEAD"])
        if code == 0 and out:
            return out
        return "main"

    def createBranch(self, branchName: str) -> bool:
        self.ensureRepo()
        code, _, _ = self.runGitCommand(["checkout", "-B", branchName])
        return code == 0

    def getRemoteUrl(self) -> str:
        code, out, _ = self.runGitCommand(["remote", "get-url", "origin"])
        if code == 0 and out:
            return out
        return ""

    def commitMilestone(self, message: str) -> bool:
        self.ensureRepo()
        self.runGitCommand(["add", "."])
        cleanMsg = message.replace('"', "'").strip()
        code, _, _ = self.runGitCommand(["commit", "-m", cleanMsg])
        return code == 0

    def createRemoteRepo(self, repoName: str, isPrivate: bool = False, description: str = "") -> str:
        if not self.token:
            print("\nA GitHub Personal Access Token (with 'repo' scope) is required to create repositories.")
            tokenInput = input("Enter GitHub Personal Access Token: ").strip()
            if not tokenInput:
                print("Repository creation aborted: No token provided.")
                return ""
            self.token = tokenInput

        payload = {
            "name": repoName,
            "private": isPrivate,
            "description": description
        }
        reqData = json.dumps(payload).encode("utf-8")
        headers = {
            "User-Agent": "Kai-GitHubAgent",
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"token {self.token}",
            "Content-Type": "application/json"
        }
        apiUrl = "https://api.github.com/user/repos"
        try:
            req = urllib.request.Request(apiUrl, data=reqData, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=15) as resp:
                resJson = json.loads(resp.read().decode("utf-8"))
                cloneUrl = resJson.get("clone_url", "")
                fullName = resJson.get("full_name", "")
                print(f"\n[GitHub] Successfully created repository '{fullName}'")
                return cloneUrl
        except urllib.error.HTTPError as err:
            errBody = err.read().decode("utf-8") if err.fp else ""
            print(f"\n[GitHub Error] Failed to create repository: HTTP {err.code} {err.reason}")
            if errBody:
                try:
                    errData = json.loads(errBody)
                    errMsg = errData.get("message", "")
                    if errMsg:
                        print(f"Details: {errMsg}")
                except Exception:
                    pass
            return ""
        except Exception as err:
            print(f"\n[GitHub Error] Failed to create repository: {err}")
            return ""

    def publish(self, goal: str, targetBranch: str = "") -> bool:
        self.ensureRepo()
        currentBranch = targetBranch or self.getCurrentBranch()
        remoteUrl = self.getRemoteUrl()

        print("\n[GitHub Publishing]")
        confirm = input("Publish and push to GitHub? (y/n): ").strip().lower()
        if confirm != "y":
            print("GitHub publishing skipped by user.")
            return False

        if remoteUrl:
            print(f"Detected remote origin: {remoteUrl}")

        print("\nRepository Destination:")
        print("1. Push to existing repository")
        print("2. Create a new remote repository on GitHub")
        repoChoice = input("Choose option (1/2) [1]: ").strip()

        if repoChoice == "2":
            folderName = self.workDir.name if self.workDir.name else "kai-project"
            defaultRepoName = folderName.replace(" ", "-").lower()
            nameInput = input(f"Enter repository name [{defaultRepoName}]: ").strip()
            chosenRepoName = nameInput if nameInput else defaultRepoName
            privInput = input("Make repository private? (y/n) [n]: ").strip().lower()
            isPrivate = privInput == "y"
            createdUrl = self.createRemoteRepo(chosenRepoName, isPrivate, goal)
            if not createdUrl:
                print("Failed to create remote repository. Publishing aborted.")
                return False
            if remoteUrl:
                self.runGitCommand(["remote", "remove", "origin"])
            self.runGitCommand(["remote", "add", "origin", createdUrl])
            remoteUrl = createdUrl
        else:
            if not remoteUrl:
                remoteInput = input("Enter remote repository URL (e.g. https://github.com/user/repo.git): ").strip()
                if not remoteInput:
                    print("Publishing cancelled: No remote repository provided.")
                    return False
                self.runGitCommand(["remote", "add", "origin", remoteInput])
                remoteUrl = remoteInput
            else:
                remoteInput = input(f"Press Enter to use [{remoteUrl}] or enter new URL: ").strip()
                if remoteInput:
                    self.runGitCommand(["remote", "set-url", "origin", remoteInput])
                    remoteUrl = remoteInput

        branchInput = input(f"Branch to push [{currentBranch}]: ").strip()
        finalBranch = branchInput if branchInput else currentBranch

        self.ensureGitignore()
        self.runGitCommand(["add", "."])
        commitMsg = f"feat: completed {goal}" if goal else "feat: verified project implementation"
        self.runGitCommand(["commit", "-m", commitMsg])
        self.runGitCommand(["branch", "-M", finalBranch])

        print(f"Pushing to {remoteUrl} on branch '{finalBranch}'...")
        code, out, err = self.runGitCommand(["push", "-u", "origin", finalBranch])
        if code != 0 and self.token and "https://" in remoteUrl and "@" not in remoteUrl:
            tokenUrl = remoteUrl.replace("https://", f"https://{self.token}@")
            self.runGitCommand(["remote", "set-url", "origin", tokenUrl])
            code, out, err = self.runGitCommand(["push", "-u", "origin", finalBranch])
            self.runGitCommand(["remote", "set-url", "origin", remoteUrl])

        if code == 0:
            print(f"\n[GitHub] Successfully pushed to {finalBranch}!")
            return True
        else:
            print(f"\n[GitHub Push Failed]:\n{err or out}")
            return False

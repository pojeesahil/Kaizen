import sys
import os
import re
import builtins
from datetime import datetime
from pathlib import Path
from typing import Optional

activeLogFile = None
originalStdout = sys.stdout
originalStderr = sys.stderr
originalInput = builtins.input

class dualWriter:
    def __init__(self, originalStream, logFile):
        self.originalStream = originalStream
        self.logFile = logFile

    def write(self, data: str) -> None:
        self.originalStream.write(data)
        self.originalStream.flush()
        cleanData = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", data)
        try:
            self.logFile.write(cleanData)
            self.logFile.flush()
        except Exception:
            pass

    def flush(self) -> None:
        self.originalStream.flush()
        try:
            self.logFile.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        if hasattr(self.originalStream, "isatty"):
            return self.originalStream.isatty()
        return False

    def fileno(self) -> int:
        if hasattr(self.originalStream, "fileno"):
            return self.originalStream.fileno()
        return 1

def loggedInput(promptStr: str = "") -> str:
    userVal = originalInput(promptStr)
    if activeLogFile:
        try:
            cleanPrompt = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", str(promptStr))
            activeLogFile.write(f"{cleanPrompt}{userVal}\n")
            activeLogFile.flush()
        except Exception:
            pass
    return userVal

def startLogging(customDir: Optional[Path] = None) -> Path:
    global activeLogFile

    if customDir is not None:
        logDir = customDir
    else:
        logDir = Path(__file__).resolve().parent.parent / "logs"

    logDir.mkdir(parents=True, exist_ok=True)
    timeMarker = datetime.now().strftime("%Y%m%d_%H%M%S")
    logFilePath = logDir / f"session_{timeMarker}.log"
    latestPath = logDir / "latest.log"

    activeLogFile = open(logFilePath, "a", encoding="utf-8", errors="ignore")
    latestFile = open(latestPath, "w", encoding="utf-8", errors="ignore")
    latestFile.close()

    class multiFileDualWriter:
        def __init__(self, streamTarget, primaryFile, secondaryPath):
            self.streamTarget = streamTarget
            self.primaryFile = primaryFile
            self.secondaryPath = secondaryPath

        def write(self, textData: str) -> None:
            self.streamTarget.write(textData)
            self.streamTarget.flush()
            cleanText = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", textData)
            try:
                self.primaryFile.write(cleanText)
                self.primaryFile.flush()
                with open(self.secondaryPath, "a", encoding="utf-8", errors="ignore") as f:
                    f.write(cleanText)
            except Exception:
                pass

        def flush(self) -> None:
            self.streamTarget.flush()
            try:
                self.primaryFile.flush()
            except Exception:
                pass

        def isatty(self) -> bool:
            if hasattr(self.streamTarget, "isatty"):
                return self.streamTarget.isatty()
            return False

        def fileno(self) -> int:
            if hasattr(self.streamTarget, "fileno"):
                return self.streamTarget.fileno()
            return 1

    sys.stdout = multiFileDualWriter(originalStdout, activeLogFile, latestPath)
    sys.stderr = multiFileDualWriter(originalStderr, activeLogFile, latestPath)
    builtins.input = loggedInput

    print(f"[Logging] Session output is being saved to: {logFilePath}")
    return logFilePath

def stopLogging() -> None:
    global activeLogFile
    sys.stdout = originalStdout
    sys.stderr = originalStderr
    builtins.input = originalInput
    if activeLogFile:
        try:
            activeLogFile.close()
        except Exception:
            pass
        activeLogFile = None

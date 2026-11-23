const { app, BrowserWindow } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const http = require('http');

let mainWindow = null;
let pythonProcess = null;
const SERVER_URL = 'http://127.0.0.1:8765';

function checkServerReady(cb) {
  http.get(SERVER_URL, (res) => {
    cb(true);
  }).on('error', () => {
    cb(false);
  });
}

function startPythonBackend(callback) {
  // Check if server is already running
  checkServerReady((ready) => {
    if (ready) {
      console.log('[Electron] Python backend already active on ' + SERVER_URL);
      return callback();
    }

    console.log('[Electron] Spawning python gui_server.py...');
    const pythonExe = process.platform === 'win32'
      ? path.join(__dirname, '..', '.venv', 'Scripts', 'python.exe')
      : path.join(__dirname, '..', '.venv', 'bin', 'python');

    const scriptPath = path.join(__dirname, '..', 'gui_server.py');

    pythonProcess = spawn(pythonExe, [scriptPath], {
      cwd: path.join(__dirname, '..'),
      stdio: 'pipe'
    });

    pythonProcess.stdout.on('data', (d) => console.log(`[Python] ${d}`));
    pythonProcess.stderr.on('data', (d) => console.error(`[Python Err] ${d}`));

    // Poll until server is ready
    let attempts = 0;
    const interval = setInterval(() => {
      attempts++;
      checkServerReady((isReady) => {
        if (isReady || attempts > 20) {
          clearInterval(interval);
          callback();
        }
      });
    }, 500);
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1320,
    height: 860,
    minWidth: 1024,
    minHeight: 700,
    title: 'Kaizen — Autonomous Software Engineering Swarm',
    backgroundColor: '#0b0f17',
    autoHideMenuBar: true,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true
    }
  });

  mainWindow.loadURL(SERVER_URL);

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

app.whenReady().then(() => {
  startPythonBackend(() => {
    createWindow();
  });

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('will-quit', () => {
  if (pythonProcess) {
    try {
      pythonProcess.kill();
    } catch (e) {}
  }
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

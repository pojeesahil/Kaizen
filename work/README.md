# Retro Neon Snake 🐍✨

A modern, high-fidelity, responsive single-file HTML5 Snake game built with Canvas, CSS variables, and the Web Audio API. Featuring a sleek cyberpunk neon aesthetic, dynamic particle effects, screen shake, sound effects synthesized on-the-fly, and mobile-friendly virtual controls.

---

## 🎮 How to Play

### 🚀 Browser Launch Instructions
Since the entire game is self-contained within a single file (`index.html`), there are **no external dependencies, build steps, or local servers required**.

1. **Locate the file**: Find `index.html` in the project directory.
2. **Open in Browser**:
   - **Double-click** the `index.html` file to open it in your default web browser.
   - Alternatively, **drag and drop** `index.html` into any open browser window (Chrome, Firefox, Safari, Edge, Opera).
3. **Start Playing**: Click the **"Start Game"** button on the neon overlay or press **Space / Enter** to begin!

---

## 🕹️ Control Schemes

The game supports multiple input methods for a seamless experience across desktop and mobile devices.

### ⌨️ Keyboard Controls (Desktop)
Use either standard WASD or Arrow keys to steer the snake.

| Action | Primary Key | Secondary Key |
| :--- | :--- | :--- |
| **Steer Up** | `W` | `▲ Arrow Up` |
| **Steer Down** | `S` | `▼ Arrow Down` |
| **Steer Left** | `A` | `◀ Arrow Left` |
| **Steer Right** | `D` | `▶ Arrow Right` |
| **Pause / Resume** | `Spacebar` | — |
| **Confirm / Restart** | `Enter` | `Spacebar` |

*Note: The game engine features input buffering and direction-reversal prevention, meaning you cannot accidentally crash into yourself by pressing the opposite direction.*

### 📱 Virtual D-Pad (Mobile & Tablets)
When played on a mobile device or a narrow screen, a virtual **D-Pad** automatically appears below the game board:
- Tap **▲** to steer Up.
- Tap **◀** to steer Left.
- Tap **▶** to steer Right.
- Tap **▼** to steer Down.

---

## 🌟 Core Gameplay Mechanics

1. **The Objective**: Navigate the grid, consume glowing energy cores to grow in length, and achieve the highest score possible without crashing.
2. **Energy Cores (Food)**:
   - **Normal Core (Red)**: Spawns randomly. Consuming it awards **10 points**, increases your length by 1 segment, triggers a subtle screen shake, and spawns red neon particles.
   - **Special Core (Golden)**: Has a **15% chance** of spawning. Consuming it awards **30 points**, triggers a stronger screen shake, flashes the game border, and spawns golden particles.
3. **Collision Rules**:
   - **Wall Collision**: Crashing into the outer boundary of the 20x20 grid results in an immediate **Game Over**.
   - **Self Collision**: Biting any part of your own tail results in an immediate **Game Over**.
4. **Difficulty Settings**:
   You can change the speed of the game at any time using the dropdown menu:
   - **Easy**: 140ms per tick (Relaxed pace)
   - **Medium**: 100ms per tick (Standard speed, default)
   - **Hard**: 70ms per tick (Fast-paced challenge)
   - **Insane**: 45ms per tick (Extreme reflexes required)
5. **Score Persistence**:
   Your high score is automatically saved to your browser's `localStorage` under the key `neon_snake_high_score`. It will persist even if you refresh or close the browser.
6. **Synthesized Audio**:
   The game features retro sound effects synthesized in real-time using the browser's **Web Audio API** (no external audio files needed!). You can toggle sound on/off using the speaker button (`🔊` / `🔇`).

---

## 🛠️ Technical Architecture

The codebase is structured as a single-file application inside `index.html` for maximum portability and performance. Below is an overview of the architectural components:

```
+-----------------------------------------------------------------+
|                           index.html                            |
|                                                                 |
|  +-------------------+  +------------------+  +--------------+  |
|  |    CSS Styles     |  |    HTML Layout   |  |  Audio (SFX) |  |
|  | (Neon Glow, Flex) |  | (Canvas, Panels) |  | (Web Audio)  |  |
|  +-------------------+  +------------------+  +--------------+  |
|                                                                 |
|  +-----------------------------------------------------------+  |
|  |                     JavaScript Engine                     |  |
|  |                                                           |  |
|  |  +------------------+  +------------------+  +---------+  |  |
|  |  |    Game Loop     |  | State Management |  | Drawing |  |  |
|  |  | (rAF, Tick Rate) |  |  (START, PLAY)   |  | Engine  |  |  |
|  |  +------------------+  +------------------+  +---------+  |  |
|  |                                                           |  |
|  |  +------------------+  +------------------+               |  |
|  |  | Particle System  |  | Input Handlers   |               |  |
|  |  |  (Visual FX)     |  | (Keys, Touch)    |               |  |
|  |  +------------------+  +------------------+               |  |
|  +-----------------------------------------------------------+  |
+-----------------------------------------------------------------+
```

### 1. Game Loop & Timing
The game uses `requestAnimationFrame` to drive the rendering loop at the monitor's native refresh rate (typically 60Hz or higher). 
- To decouple the snake's movement speed from the frame rate, a **tick-based timer** (`lastTickTime`) is used.
- The game state updates only when the elapsed time since the last tick exceeds the threshold defined by the selected difficulty (e.g., 100ms for Medium).
- This ensures smooth particle animations and screen shake transitions while keeping the snake's movement perfectly consistent.

### 2. State Management
The game transitions between four distinct states:
- `START`: Displays the title screen overlay.
- `PLAYING`: The active gameplay state where inputs are processed and the snake moves.
- `PAUSED`: Freezes the game tick while keeping the canvas rendered.
- `GAMEOVER`: Displays the game over screen with the crash reason and a restart button.

### 3. Rendering Engine (Canvas API)
- **High-DPI Support**: The canvas automatically detects the device's pixel ratio (`window.devicePixelRatio`) and scales the backing store accordingly to prevent blurry rendering on Retina and high-res screens.
- **Glow Effects**: Leverages Canvas `shadowBlur` and `shadowColor` properties to create the signature neon glow around the snake's head, body segments, and energy cores.
- **Screen Shake**: Implemented by translating the canvas context (`ctx.translate(dx, dy)`) by a decaying random offset whenever a collision or consumption event occurs.

### 4. Audio Synthesizer (`SoundEffects` Class)
Instead of loading heavy `.mp3` or `.wav` files, the game utilizes the **Web Audio API** to synthesize sound effects programmatically:
- **Eat Sound**: A sine wave oscillator that ramps exponentially from 300Hz to 800Hz over 0.15 seconds.
- **Move Sound**: A short, low-frequency triangle wave oscillator to provide subtle tactile feedback.
- **Game Over Sound**: A sawtooth wave oscillator that slides down from 150Hz to 40Hz to create a dramatic crash effect.

### 5. Particle System
When the snake eats an energy core, a burst of `Particle` instances is spawned at the core's coordinates. Each particle is updated independently with:
- Random velocity vectors (`vx`, `vy`).
- Fading opacity (`alpha` decay).
- Custom neon colors matching the consumed core.

---

## 🎨 Customization Guide

Want to tweak the game or add new features? Here are some quick code modifications you can make in `index.html`:

### Change Grid Size
To make the game board larger or smaller, modify the grid constants:
```javascript
const GRID_SIZE = 20; // Size of each tile in pixels
const TILE_COUNT = 20; // Number of tiles along each axis (20x20 grid)
```

### Customize Colors
The visual theme is controlled entirely by CSS custom properties at the top of the file. You can change these to create your own color scheme (e.g., Matrix green, Synthwave pink, or Monochromatic):
```css
:root {
    --bg-color: #0d0e15;
    --panel-bg: #161824;
    --accent-color: #00ffcc;      /* Neon Cyan */
    --snake-color: #39ff14;       /* Neon Green */
    --food-color: #ff0055;        /* Neon Red */
}
```

### Adjust Speeds
To make the game faster or slower, modify the millisecond values in the `SPEEDS` object:
```javascript
const SPEEDS = {
    easy: 140,
    medium: 100,
    hard: 70,
    insane: 45
};
```

---

## 📜 License
This project is open-source and free to use, modify, and distribute. Have fun playing and customizing! 🚀
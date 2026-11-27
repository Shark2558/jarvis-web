---
page: pg_screen_construct
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/static/console.html": "d26e202e4e9aa526"
---
## In plain words
Construct is the console's hologram: three wireframe shapes nested inside each other, slowly turning above a projector base while a glowing plane sweeps up and down through them. It does no work for you; it is there for the look of the deck, like the Core in the middle of the screen. Under it, three readings show the real numbers of the drawing: Vertices, Edges and Frame rate (`src/jarvis/api/static/console.html`).

## Example (made up)
On a slow Friday evening you open Construct from the More sheet on your phone. The hologram starts turning, and the readings show the corner and edge counts and a frame rate of about 30. You switch the look to Day in Appearance and the hologram's colours follow. When you close the panel, the drawing stops and your phone's battery is spared.

## How it works
The panel in `src/jarvis/api/static/console.html` holds a flat picture of the shapes and a drawing area for the moving 3D version. The 3D version is drawn only when your browser supports WebGL2 and the panel is actually on screen; otherwise the flat picture stays (`src/jarvis/api/static/console.html`). On a phone nothing 3D is loaded until you open this panel (`src/jarvis/api/static/console.html`). The Vertices and Edges readings are counted from the shapes as they are built, and Frame rate shows how fast the drawing runs (`src/jarvis/api/static/console.html`). The drawing follows your chosen look and motion setting, and stands still when motion is set to calm or off (`src/jarvis/api/static/console.html`).

## What it costs
Construct costs nothing: it is drawn by your own browser with no server call (`src/jarvis/api/static/console.html`). On a weak device the console lowers the frame rate, then falls back to the flat picture (`src/jarvis/api/static/console.html`).

## When it fails
If the browser has no WebGL2, the flat picture is shown instead, and the readings give its own counts with "CSS" as the frame rate (`src/jarvis/api/static/console.html`). Nothing else in the console depends on this panel.

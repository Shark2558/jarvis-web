// android/app/src/main/java/io/github/shark2558/jarvis/shell/TalkTileService.kt
// R7 D9: "Talk to JARVIS" in the pull-down shade. One tap opens JARVIS with the mic button ready
// (do=talk); one more tap on that button starts listening. The tile never touches a microphone:
// listening always takes the owner's tap in the page. On a locked phone it asks to unlock first.
package io.github.shark2558.jarvis.shell

import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import io.github.shark2558.jarvis.link.AppState

class TalkTileService : TileService() {
    override fun onTileAdded() {
        super.onTileAdded()
        AppState(this).setTile(AppState.TILE_TALK, true)
    }

    override fun onTileRemoved() {
        super.onTileRemoved()
        AppState(this).setTile(AppState.TILE_TALK, false)
    }

    override fun onStartListening() {
        super.onStartListening()
        val tile = qsTile ?: return
        tile.state = Tile.STATE_INACTIVE
        tile.updateTile()
    }

    override fun onClick() {
        super.onClick()
        val open = Runnable {
            Tiles.open(this, ScreenLauncherActivity.launchIntent(this, "talk"), Tiles.REQUEST_TALK)
        }
        if (isLocked) unlockAndRun(open) else open.run()
    }
}

// android/app/src/main/java/io/github/shark2558/jarvis/shell/SosTileService.kt
// R7 D19: the SOS tile. It opens the native SOS screen, which counts down 10 seconds with sound,
// vibration and a full-width Cancel; a cancelled countdown sends nothing. It works from the lock
// screen too (the screen then shows the countdown and nothing else).
package io.github.shark2558.jarvis.shell

import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import io.github.shark2558.jarvis.link.AppState
import io.github.shark2558.jarvis.sos.SosActivity

class SosTileService : TileService() {
    override fun onTileAdded() {
        super.onTileAdded()
        AppState(this).setTile(AppState.TILE_SOS, true)
    }

    override fun onTileRemoved() {
        super.onTileRemoved()
        AppState(this).setTile(AppState.TILE_SOS, false)
    }

    override fun onStartListening() {
        super.onStartListening()
        val tile = qsTile ?: return
        tile.state = Tile.STATE_INACTIVE
        tile.updateTile()
    }

    override fun onClick() {
        super.onClick()
        Tiles.open(this, SosActivity.fromTile(this), Tiles.REQUEST_SOS)
    }
}

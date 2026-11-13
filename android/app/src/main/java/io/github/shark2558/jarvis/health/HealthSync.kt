// android/app/src/main/java/io/github/shark2558/jarvis/health/HealthSync.kt
// R7 D17: read the last 3 days (the first time 30, Health Connect's own limit) and send one
// summary a day through the door: steps; heart rate lowest, average and highest; each night's
// sleep with minutes per stage; and the app that wrote each. No raw heart samples, no values in
// a log. Blocking: the 6-hourly job and the set-up screen call it off the main thread.
package io.github.shark2558.jarvis.health

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import io.github.shark2558.jarvis.core.DayBuilder
import io.github.shark2558.jarvis.core.Payloads
import io.github.shark2558.jarvis.link.AppState
import io.github.shark2558.jarvis.link.DoorClient
import java.time.LocalDate
import java.time.ZoneId

object HealthSync {
    enum class Outcome { SENT, NOTHING, NO_HEALTH_CONNECT, NO_PERMISSION, NOT_LINKED, FAILED }

    private const val FIRST_DAYS = 30L
    private const val ROUTINE_DAYS = 3L

    fun run(context: Context): Outcome {
        val state = AppState(context)
        if (!state.isLinked()) return Outcome.NOT_LINKED
        if (!HealthAccess.available(context)) return Outcome.NO_HEALTH_CONNECT
        val client = HealthConnectClient.getOrCreate(context)
        val granted = await { client.permissionController.getGrantedPermissions() }
        if (HealthPermissions.READ.none { it in granted }) return Outcome.NO_PERMISSION
        val zone = ZoneId.systemDefault()
        val today = LocalDate.now(zone)
        val back = if (state.lastHealthSync() == 0L) FIRST_DAYS else ROUTINE_DAYS
        val days = (0L until back).map { today.minusDays(it) }
        val built = DayBuilder(zone).build(HealthReader(client, zone, granted), days)
        if (built.all { it.steps == null && it.heart == null && it.sleep.isEmpty() }) {
            state.setLastHealthSync(System.currentTimeMillis())
            return Outcome.NOTHING
        }
        val answer = DoorClient(context).signed("health", Payloads.health(built))
        if (!answer.ok) return Outcome.FAILED
        state.setLastHealthSync(System.currentTimeMillis())
        return Outcome.SENT
    }
}

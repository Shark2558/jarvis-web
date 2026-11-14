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
import io.github.shark2558.jarvis.core.Replies
import io.github.shark2558.jarvis.link.AppState
import io.github.shark2558.jarvis.link.DoorClient
import java.time.LocalDate
import java.time.ZoneId

object HealthSync {
    /** FAILED is a wait (the job tries again); REFUSED is the door's no, with its plain `note`. */
    enum class Outcome { SENT, NOTHING, NO_HEALTH_CONNECT, NO_PERMISSION, NOT_LINKED, FAILED, REFUSED }

    data class Report(val outcome: Outcome, val note: String? = null)

    private const val FIRST_DAYS = 30L
    private const val ROUTINE_DAYS = 3L

    fun run(context: Context): Report {
        val state = AppState(context)
        if (!state.isLinked()) return Report(Outcome.NOT_LINKED)
        if (state.needsRelink()) return Report(Outcome.NOT_LINKED, Replies.NEEDS_LINKING)
        if (!HealthAccess.available(context)) return Report(Outcome.NO_HEALTH_CONNECT)
        val client = HealthConnectClient.getOrCreate(context)
        val granted = await { client.permissionController.getGrantedPermissions() }
        if (HealthPermissions.READ.none { it in granted }) return Report(Outcome.NO_PERMISSION)
        val zone = ZoneId.systemDefault()
        val today = LocalDate.now(zone)
        val back = if (state.lastHealthSync() == 0L) FIRST_DAYS else ROUTINE_DAYS
        val days = (0L until back).map { today.minusDays(it) }
        val built = DayBuilder(zone).build(HealthReader(client, zone, granted), days)
        if (built.all { it.steps == null && it.heart == null && it.sleep.isEmpty() }) {
            return Report(Outcome.NOTHING) // not stamped: the first read's 30 days are still owed
        }
        val answer = DoorClient(context).signed("health", Payloads.health(built))
        val refusal = answer.refusal ?: run {
            state.setLastHealthSync(System.currentTimeMillis())
            return Report(Outcome.SENT)
        }
        val outcome = if (Replies.worthRetry(answer.status)) Outcome.FAILED else Outcome.REFUSED
        return Report(outcome, refusal.sentence)
    }
}

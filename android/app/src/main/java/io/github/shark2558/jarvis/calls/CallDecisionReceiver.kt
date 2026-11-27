// android/app/src/main/java/io/github/shark2558/jarvis/calls/CallDecisionReceiver.kt
// R18 D: "Decline" on a call card's notification (not reachable from other apps). Declining needs
// no unlock: it can only stop a call, never start one. The signed card is checked again, then the
// decision goes to the cloud on the door, and the notification goes.
package io.github.shark2558.jarvis.calls

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import io.github.shark2558.jarvis.core.CallCommands
import io.github.shark2558.jarvis.core.CallPayloads
import io.github.shark2558.jarvis.core.CardCommand
import io.github.shark2558.jarvis.core.CommandVerdict
import io.github.shark2558.jarvis.core.DecisionEvent
import io.github.shark2558.jarvis.link.AppState

class CallDecisionReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != ACTION_DECLINE) return
        val body = intent.getStringExtra(CallTapActivity.EXTRA_BODY) ?: return
        val sig = intent.getStringExtra(CallTapActivity.EXTRA_SIG) ?: return
        val key = CallsStore(context).key() ?: return
        val device = AppState(context).deviceId() ?: return
        val checked = CallCommands.check(key, body, sig, device, CallsLink.nowS()) { false }
        val card = checked.command as? CardCommand ?: return
        if (checked.verdict != CommandVerdict.ACT) return
        CallNotices.cancel(context, CallNotices.TAG_CARD, card.cardId)
        val decision = DecisionEvent(CallPayloads.newEventId(), card.cardId, "decline", CallsLink.nowS())
        val pending = goAsync()
        val app = context.applicationContext
        CallsLink.worker.execute {
            try {
                CallsLink.pullAndAct(app, listOf(decision))
            } finally {
                pending.finish()
            }
        }
    }

    companion object {
        private const val ACTION_DECLINE = "io.github.shark2558.jarvis.calls.DECLINE"

        fun decline(context: Context, body: String, sig: String): Intent =
            Intent(context, CallDecisionReceiver::class.java)
                .setAction(ACTION_DECLINE)
                .putExtra(CallTapActivity.EXTRA_BODY, body)
                .putExtra(CallTapActivity.EXTRA_SIG, sig)
    }
}

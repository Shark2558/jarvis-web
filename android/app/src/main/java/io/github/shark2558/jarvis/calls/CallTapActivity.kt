// android/app/src/main/java/io/github/shark2558/jarvis/calls/CallTapActivity.kt
// R18 D: what a tap on a calls notification opens (not reachable from other apps; no screen of its
// own). The intent carries the signed command, and it is checked again here (the cloud's key, this
// phone, not expired), so nothing but a command the cloud signed can place a call through it.
//
//   dial     "Tap to let JARVIS call <name>": he is in front of the phone now, so Android lets the
//            call start; placed once (unless it is already on).
//   approve  a call card: first he unlocks the phone (his own lock, never skipped); then a card
//            whose number was never called opens the console's Calls panel for his passkey, and
//            any other card's approval goes to the cloud, which still decides (it may still ask
//            for the passkey, and the console opens then).
package io.github.shark2558.jarvis.calls

import android.app.Activity
import android.app.KeyguardManager
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.Toast
import io.github.shark2558.jarvis.R
import io.github.shark2558.jarvis.core.CallCommand
import io.github.shark2558.jarvis.core.CallCommands
import io.github.shark2558.jarvis.core.CardCommand
import io.github.shark2558.jarvis.core.CommandVerdict
import io.github.shark2558.jarvis.core.DecisionEvent
import io.github.shark2558.jarvis.core.CallPayloads
import io.github.shark2558.jarvis.core.DialCommand
import io.github.shark2558.jarvis.link.AppState

class CallTapActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (savedInstanceState != null) {
            finish()
            return
        }
        val body = intent?.getStringExtra(EXTRA_BODY)
        val sig = intent?.getStringExtra(EXTRA_SIG)
        val cmd = if (body != null && sig != null) checked(body, sig) else null
        when {
            cmd is DialCommand && intent?.action == ACTION_DIAL -> whenUnlocked { dial(cmd) }
            cmd is CardCommand && intent?.action == ACTION_APPROVE -> whenUnlocked { approve(cmd) }
            else -> {
                Toast.makeText(this, R.string.calls_expired, Toast.LENGTH_LONG).show()
                finish()
            }
        }
    }

    /** The command, if the cloud signed it for this phone and it has not run out. A dial that was
     *  offered as this notification was marked as handled when it was offered: that is expected. */
    private fun checked(body: String, sig: String): CallCommand? {
        val key = CallsStore(this).key() ?: return null
        val device = AppState(this).deviceId() ?: return null
        val c = CallCommands.check(key, body, sig, device, CallsLink.nowS()) { false }
        return if (c.verdict == CommandVerdict.ACT) c.command else null
    }

    private fun dial(cmd: DialCommand) {
        CallNotices.cancel(this, CallNotices.TAG_DIAL, cmd.callId)
        val store = CallsStore(this)
        val first = synchronized(CallsStore.LOCK) {
            val tapped = TAPPED + cmd.head.id
            if (store.acted(tapped)) false else true.also { store.markActed(tapped, cmd.head.exp, CallsLink.nowS()) }
        }
        if (!first) { // a second tap on the same notice places nothing
            finish()
            return
        }
        val placed = CallActions.place(this, cmd)
        val result = CallActions.result(cmd, placed, if (placed) "placed" else "refused")
        CallsLink.pullSoon(this, listOf(result))
        if (!placed) Toast.makeText(this, R.string.calls_not_placed, Toast.LENGTH_LONG).show()
        finish()
    }

    private fun approve(cmd: CardCommand) {
        CallNotices.cancel(this, CallNotices.TAG_CARD, cmd.cardId)
        if (cmd.passkey) {
            openConsole()
            return
        }
        // the answer can take a few seconds: this see-through screen goes at once, the words follow
        val app = applicationContext
        val decision = DecisionEvent(CallPayloads.newEventId(), cmd.cardId, "approve", CallsLink.nowS())
        CallsLink.worker.execute {
            val answer = CallsLink.pullAndAct(app, listOf(decision))
            val outcome = answer?.decisions?.firstOrNull { it.first == cmd.cardId }?.second
            if (outcome == "passkey_needed") CallNotices.passkey(app, cmd) else say(app, outcome)
        }
        finish()
    }

    private fun openConsole() {
        startActivity(Intent(this, CallsLauncherActivity::class.java))
        finish()
    }

    private fun whenUnlocked(action: () -> Unit) {
        val keyguard = getSystemService(KeyguardManager::class.java)
        if (keyguard == null || !keyguard.isKeyguardLocked) {
            action()
            return
        }
        keyguard.requestDismissKeyguard(
            this,
            object : KeyguardManager.KeyguardDismissCallback() {
                override fun onDismissSucceeded() {
                    action()
                }

                override fun onDismissCancelled() {
                    finish()
                }

                override fun onDismissError() {
                    finish()
                }
            },
        )
    }

    companion object {
        /** A plain sentence for the outcome of an approval, on the main thread. */
        private fun say(context: Context, outcome: String?) {
            val words = when (outcome) {
                "approved" -> R.string.calls_approved
                "gone" -> R.string.calls_expired
                else -> R.string.calls_not_reached
            }
            Handler(Looper.getMainLooper()).post { Toast.makeText(context, words, Toast.LENGTH_LONG).show() }
        }

        private const val ACTION_DIAL = "io.github.shark2558.jarvis.calls.DIAL"
        private const val ACTION_APPROVE = "io.github.shark2558.jarvis.calls.APPROVE"
        private const val TAPPED = "t_"
        const val EXTRA_BODY = "body"
        const val EXTRA_SIG = "sig"

        fun dial(context: Context, body: String, sig: String): Intent = of(context, ACTION_DIAL, body, sig)

        fun approve(context: Context, body: String, sig: String): Intent = of(context, ACTION_APPROVE, body, sig)

        private fun of(context: Context, action: String, body: String, sig: String): Intent =
            Intent(context, CallTapActivity::class.java)
                .setAction(action)
                .putExtra(EXTRA_BODY, body)
                .putExtra(EXTRA_SIG, sig)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_NO_HISTORY)
    }
}

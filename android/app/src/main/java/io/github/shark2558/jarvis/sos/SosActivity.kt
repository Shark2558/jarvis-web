// android/app/src/main/java/io/github/shark2558/jarvis/sos/SosActivity.kt
// R7 D19: the native SOS screen (from the SOS tile, the SOS shortcut, or "Test SOS" in set-up).
// A 10-second countdown with sound, vibration and a full-width Cancel takes the hold's place;
// core's SosMachine runs it, and a cancelled countdown sends nothing at all. At the end: the
// door's SOS (Telegram to each contact, by the server), and the phone's own SMS app opened with
// every number and the fixed message for the owner to press Send (no SMS permission; it works
// with no internet). Then: call the first contact, call 112, "I'm safe". The location is asked
// for once, 10 seconds at most, and travels only in the SOS body and the text. On the lock screen
// it shows the countdown and no names. It is not an emergency service, and it says so.
// One press is at most one send: the screen survives a recreation (its state is saved, the send
// is claimed once per press id in the process-wide ledger), a new tile press restarts a finished
// or cancelled screen (onNewIntent) but never a real countdown or send in progress, and the 112
// and text-message buttons are on screen at every moment. Leaving the screen for good during the
// countdown cancels it (the countdown is the owner's cancel window); the screen stays on until it ends.
package io.github.shark2558.jarvis.sos

import android.app.Activity
import android.app.AlertDialog
import android.app.KeyguardManager
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.media.AudioManager
import android.media.ToneGenerator
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import io.github.shark2558.jarvis.R
import io.github.shark2558.jarvis.core.Fix
import io.github.shark2558.jarvis.core.Launch
import io.github.shark2558.jarvis.core.Payloads
import io.github.shark2558.jarvis.core.PressLedger
import io.github.shark2558.jarvis.core.SosKind
import io.github.shark2558.jarvis.core.SosMachine
import io.github.shark2558.jarvis.core.SosPress
import io.github.shark2558.jarvis.core.SosState
import io.github.shark2558.jarvis.core.SosText
import io.github.shark2558.jarvis.link.AppState
import io.github.shark2558.jarvis.link.DoorClient
import io.github.shark2558.jarvis.link.SosBook
import io.github.shark2558.jarvis.ui.Look
import io.github.shark2558.jarvis.ui.SystemBars
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException
import java.security.GeneralSecurityException
import java.time.ZoneId
import java.util.UUID
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

class SosActivity : Activity() {
    private data class Answer(val ok: Boolean, val reached: Int, val why: String)

    private lateinit var machine: SosMachine
    private var pressId = ""
    private lateinit var count: TextView
    private lateinit var status: TextView
    private lateinit var where: TextView
    private lateinit var after: View
    private lateinit var cancelButton: Button
    private lateinit var firstCall: Button
    private lateinit var notice: TextView
    private val ticker = Handler(Looper.getMainLooper())
    private val io: ExecutorService = Executors.newSingleThreadExecutor()
    private var location: OneShotLocation? = null
    private var fix: Fix? = null
    private var locating = false
    private var kind = SosKind.REAL
    private var book: SosBook? = null
    private var tone: ToneGenerator? = null
    private var lastBeep = -1L

    private val tick = object : Runnable {
        override fun run() {
            val now = SystemClock.elapsedRealtime()
            machine.tick(now)
            render(now)
            val s = machine.state
            if (s is SosState.Counting || s == SosState.Sending) ticker.postDelayed(this, TICK_MS)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setShowWhenLocked(true)
        setTurnScreenOn(true)
        setContentView(R.layout.activity_sos)
        SystemBars.pad(this, findViewById(R.id.sos_root))
        Look.fonts(this, findViewById(R.id.sos_root))
        count = findViewById(R.id.sos_count)
        status = findViewById(R.id.sos_status)
        where = findViewById(R.id.sos_location)
        after = findViewById(R.id.sos_after)
        cancelButton = findViewById(R.id.sos_cancel)
        firstCall = findViewById(R.id.sos_call_first)
        notice = findViewById(R.id.sos_notice)
        // a press that already sent (even before a restart of the process) is never sent twice
        AppState(this).lastSosPress()?.let { ledger.claim(it) }
        book = ContactsVault.load(this)
        wireButtons()
        if (savedInstanceState?.containsKey(KEY_PRESS) == true) {
            resume(savedInstanceState)
        } else {
            begin(kindOf(intent), newPressId())
        }
    }

    /** A new press reached the screen that is already open (the tile or shortcut pressed again). */
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        val next = kindOf(intent)
        // a finished or cancelled screen starts again; a real countdown or send in progress stands
        if (SosPress.startsFresh(machine.state, kind, next)) {
            location?.stop()
            begin(next, newPressId())
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        val saved = machine.saved()
        outState.putString(KEY_PRESS, saved.pressId)
        outState.putInt(KEY_PHASE, saved.phase)
        outState.putLong(KEY_UNTIL, saved.untilMs)
        outState.putInt(KEY_REACHED, saved.reached)
        outState.putString(KEY_WHY, saved.why)
        outState.putBoolean(KEY_TEST, kind == SosKind.TEST)
    }

    private fun kindOf(from: Intent?): SosKind =
        if (from?.getBooleanExtra(EXTRA_TEST, false) == true) SosKind.TEST else SosKind.REAL

    private fun newPressId(): String = UUID.randomUUID().toString()

    private fun newMachine(): SosMachine = SosMachine(kind, 0L, COUNTDOWN_MS, pressId, ledger) { k -> sendSos(k) }

    private fun showKind() {
        findViewById<TextView>(R.id.sos_title).setText(if (kind == SosKind.TEST) R.string.sos_title_test else R.string.sos_title)
        // a test never offers the real text message, so no test can reach the family by SMS
        findViewById<View>(R.id.sos_text).visibility = if (kind == SosKind.TEST) View.GONE else View.VISIBLE
    }

    /** A fresh press: a new id, a new machine, a 10-second countdown. */
    private fun begin(next: SosKind, id: String) {
        kind = next
        pressId = id
        fix = null
        lastBeep = -1L
        after.visibility = View.GONE
        notice.text = ""
        count.text = ""
        cancelButton.setText(R.string.sos_cancel)
        showKind()
        machine = newMachine()
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) // the timeout must not end the countdown
        startLocation()
        machine.startCountdown(SystemClock.elapsedRealtime())
        ticker.removeCallbacks(tick)
        ticker.post(tick)
    }

    /** The same press after a recreation: the machine comes back as it was (see SosMachine.restore). */
    private fun resume(saved: Bundle) {
        kind = if (saved.getBoolean(KEY_TEST)) SosKind.TEST else SosKind.REAL
        pressId = saved.getString(KEY_PRESS).orEmpty()
        val state = SosMachine.Saved(
            pressId,
            saved.getInt(KEY_PHASE),
            saved.getLong(KEY_UNTIL),
            saved.getInt(KEY_REACHED),
            saved.getString(KEY_WHY).orEmpty(),
        )
        showKind()
        machine = SosMachine.restore(state, kind, 0L, COUNTDOWN_MS, SystemClock.elapsedRealtime(), ledger) { k -> sendSos(k) }
        if (machine.state is SosState.Counting) {
            window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            startLocation()
        }
        ticker.post(tick)
    }

    override fun onDestroy() {
        ticker.removeCallbacks(tick)
        if (!isChangingConfigurations) {
            val counting = machine.state is SosState.Counting
            machine.cancel(SystemClock.elapsedRealtime()) // leaving sends nothing
            if (counting) Toast.makeText(applicationContext, R.string.sos_cancelled, Toast.LENGTH_SHORT).show()
        }
        location?.stop()
        tone?.release()
        io.shutdown() // a send already started still finishes
        super.onDestroy()
    }

    private fun wireButtons() {
        cancelButton.setOnClickListener {
            if (machine.state is SosState.Counting) {
                machine.cancel(SystemClock.elapsedRealtime())
                render(SystemClock.elapsedRealtime())
            } else {
                finish()
            }
        }
        findViewById<Button>(R.id.sos_text).setOnClickListener { openText() }
        findViewById<Button>(R.id.sos_call_112).setOnClickListener { dial(EMERGENCY) }
        firstCall.setOnClickListener {
            val first = book?.contacts?.firstOrNull()
            if (first != null) dial(first.phone)
        }
        findViewById<Button>(R.id.sos_safe).setOnClickListener { confirmSafe() }
        val first = book?.contacts?.firstOrNull()
        firstCall.visibility = if (first == null) View.GONE else View.VISIBLE
        if (first != null && !locked()) firstCall.text = getString(R.string.sos_call_first, first.label)
    }

    private fun startLocation() {
        val finder = OneShotLocation(this)
        location = finder
        if (!finder.granted()) {
            renderLocation()
            return
        }
        locating = true
        renderLocation()
        finder.request(LOCATION_MS) { found ->
            fix = found
            locating = false
            renderLocation()
        }
    }

    /** The machine's one send effect, and "I'm safe" after it: the only way to the door's SOS. */
    private fun sendSos(k: SosKind) {
        val at = System.currentTimeMillis() / MILLIS
        val place = fix
        val press = pressId
        if (k != SosKind.SAFE) AppState(this).setLastSosPress(press) // kept: this press has sent
        if (k == SosKind.REAL) openText()
        io.execute {
            val answer = try {
                if (!AppState(this).isLinked()) {
                    Answer(false, -1, NOT_LINKED)
                } else {
                    val reply = DoorClient(this).signed("sos", Payloads.sos(k, at, place, if (k == SosKind.SAFE) null else press))
                    val refusal = reply.refusal
                    when {
                        refusal == null -> Answer(true, reachedOf(reply.body), "")
                        else -> Answer(false, -1, refusal.sentence)
                    }
                }
            } catch (e: IOException) {
                Answer(false, -1, UNSURE) // it may have gone before the answer was lost
            } catch (e: GeneralSecurityException) {
                Answer(false, -1, FAILED)
            } catch (e: RuntimeException) {
                Answer(false, -1, FAILED)
            }
            if (k != SosKind.SAFE) ledger.record(press, PressLedger.Outcome(answer.ok, answer.reached, answer.why))
            runOnUiThread { answered(k, answer, press) }
        }
    }

    private fun answered(k: SosKind, answer: Answer, press: String) {
        if (isFinishing || isDestroyed) return
        if (k == SosKind.SAFE) {
            status.setText(if (answer.ok) R.string.sos_safe_sent else R.string.sos_failed)
            return
        }
        if (press != pressId) return // the answer of an older press
        machine.done(answer.ok, answer.reached, answer.why)
        render(SystemClock.elapsedRealtime())
    }

    private fun render(now: Long) {
        when (val s = machine.state) {
            is SosState.Counting -> {
                val left = machine.remainingSeconds(now)
                count.text = getString(R.string.sos_count, left.toInt())
                val words = if (kind == SosKind.TEST) R.plurals.sos_counting_test else R.plurals.sos_counting
                status.text = resources.getQuantityString(words, left.toInt(), left.toInt())
                beep(left)
            }
            is SosState.Sending -> {
                count.text = ""
                status.setText(R.string.sos_sending)
                showAfter()
            }
            is SosState.Sent -> {
                status.text = if (s.reached >= 0) {
                    resources.getQuantityString(R.plurals.sos_sent, s.reached, s.reached)
                } else {
                    getString(R.string.sos_sent_plain)
                }
                showAfter()
            }
            is SosState.Failed -> {
                status.text = when (s.why) {
                    NOT_LINKED -> getString(R.string.sos_not_linked)
                    UNSURE -> getString(R.string.sos_unsure)
                    FAILED -> getString(R.string.sos_failed)
                    else -> getString(R.string.sos_then_call, s.why)
                }
                showAfter()
            }
            is SosState.Cancelled -> {
                count.text = ""
                status.setText(R.string.sos_cancelled)
                location?.stop()
                cancelButton.setText(R.string.sos_close)
            }
            else -> Unit
        }
        if (machine.state !is SosState.Counting) window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    private fun renderLocation() {
        val found = fix
        where.text = when {
            locating -> getString(R.string.sos_locating)
            found != null -> getString(R.string.sos_located, found.accuracyM.toInt())
            else -> getString(R.string.sos_no_location)
        }
    }

    private fun showAfter() {
        // "I'm safe" tells the family the real SOS is over: a test has no such message to take back
        after.visibility = if (kind == SosKind.REAL) View.VISIBLE else View.GONE
        cancelButton.setText(R.string.sos_close)
    }

    private fun openText() {
        val saved = book
        val uri = saved?.let { b -> SosText.smsUri(b.contacts.map { it.phone }) }
        if (saved == null || uri == null) {
            notice.setText(R.string.sos_no_numbers)
            return
        }
        val message = SosText.message(saved.label, fix, ZoneId.systemDefault())
        val intent = Intent(Intent.ACTION_SENDTO, Uri.parse(uri)).putExtra(SMS_BODY, message)
        whenUnlocked { start(intent) }
    }

    private fun dial(number: String) {
        val clean = SosText.cleanNumber(number) ?: return
        whenUnlocked { start(Intent(Intent.ACTION_DIAL, Uri.parse("tel:$clean"))) }
    }

    private fun confirmSafe() {
        if (kind != SosKind.REAL) return // a test never sends the real "I'm safe"
        AlertDialog.Builder(this)
            .setMessage(R.string.sos_safe_ask)
            .setPositiveButton(R.string.sos_safe_send) { _, _ -> sendSos(SosKind.SAFE) }
            .setNegativeButton(R.string.sos_safe_not_now, null)
            .show()
    }

    private fun start(intent: Intent) {
        try {
            startActivity(intent)
        } catch (e: ActivityNotFoundException) {
            notice.setText(R.string.sos_no_app)
        }
    }

    private fun locked(): Boolean = getSystemService(KeyguardManager::class.java)?.isKeyguardLocked == true

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
                    notice.setText(R.string.sos_unlock_needed)
                }

                override fun onDismissError() {
                    notice.setText(R.string.sos_unlock_needed)
                }
            },
        )
    }

    private fun beep(left: Long) {
        if (left == lastBeep || left <= 0L) return
        lastBeep = left
        try {
            val generator = tone ?: ToneGenerator(AudioManager.STREAM_ALARM, TONE_VOLUME).also { tone = it }
            generator.startTone(ToneGenerator.TONE_PROP_BEEP, BEEP_MS)
        } catch (e: RuntimeException) {
            // no sound on this phone: the vibration and the screen still count down
        }
        vibrator()?.vibrate(VibrationEffect.createOneShot(BUZZ_MS, VibrationEffect.DEFAULT_AMPLITUDE))
    }

    private fun vibrator(): Vibrator? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            getSystemService(VibratorManager::class.java)?.defaultVibrator
        } else {
            getSystemService(Vibrator::class.java)
        }

    private fun reachedOf(body: String): Int = try {
        JSONObject(body).optInt("reached", -1)
    } catch (e: JSONException) {
        -1
    }

    companion object {
        const val EXTRA_TEST = "io.github.shark2558.jarvis.extra.TEST"
        private const val COUNTDOWN_MS = 10_000L
        private const val LOCATION_MS = 10_000L
        private const val TICK_MS = 100L
        private const val MILLIS = 1000L
        private const val BEEP_MS = 150
        private const val BUZZ_MS = 120L
        private const val TONE_VOLUME = 80
        private const val EMERGENCY = "112"
        private const val SMS_BODY = "sms_body"
        private const val NOT_LINKED = "not linked"
        private const val UNSURE = "unsure"
        private const val FAILED = "failed"
        private const val KEY_PRESS = "press"
        private const val KEY_PHASE = "phase"
        private const val KEY_UNTIL = "until"
        private const val KEY_REACHED = "reached"
        private const val KEY_WHY = "why"
        private const val KEY_TEST = "test"

        /** One ledger for the process: a press id sends once, whichever screen holds it. */
        private val ledger = PressLedger()

        fun fromTile(context: Context): Intent =
            Intent(context, SosActivity::class.java).setAction(Launch.ACTION_PREFIX + "SOS")

        fun test(context: Context): Intent =
            Intent(context, SosActivity::class.java).putExtra(EXTRA_TEST, true)
    }
}

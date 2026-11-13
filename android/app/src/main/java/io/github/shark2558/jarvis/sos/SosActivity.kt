// android/app/src/main/java/io/github/shark2558/jarvis/sos/SosActivity.kt
// R7 D19: the native SOS screen (from the SOS tile, the SOS shortcut, or "Test SOS" in set-up).
// A 10-second countdown with sound, vibration and a full-width Cancel takes the hold's place;
// core's SosMachine runs it, and a cancelled countdown sends nothing at all. At the end: the
// door's SOS (Telegram to each contact, by the server), and the phone's own SMS app opened with
// every number and the fixed message for the owner to press Send (no SMS permission; it works
// with no internet). Then: call the first contact, call 112, "I'm safe". The location is asked
// for once, 10 seconds at most, and travels only in the SOS body and the text. On the lock screen
// it shows the countdown and no names. It is not an emergency service, and it says so.
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
import android.widget.Button
import android.widget.TextView
import io.github.shark2558.jarvis.R
import io.github.shark2558.jarvis.core.Fix
import io.github.shark2558.jarvis.core.Launch
import io.github.shark2558.jarvis.core.Payloads
import io.github.shark2558.jarvis.core.SosKind
import io.github.shark2558.jarvis.core.SosMachine
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
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

class SosActivity : Activity() {
    private data class Answer(val ok: Boolean, val reached: Int, val why: String)

    private lateinit var machine: SosMachine
    private lateinit var count: TextView
    private lateinit var status: TextView
    private lateinit var where: TextView
    private lateinit var after: View
    private lateinit var cancelButton: Button
    private lateinit var firstCall: Button
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
            if (machine.state is SosState.Counting) ticker.postDelayed(this, TICK_MS)
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
        kind = if (intent?.getBooleanExtra(EXTRA_TEST, false) == true) SosKind.TEST else SosKind.REAL
        findViewById<TextView>(R.id.sos_title).setText(if (kind == SosKind.TEST) R.string.sos_title_test else R.string.sos_title)
        book = ContactsVault.load(this)
        wireButtons()
        machine = SosMachine(kind, 0L, COUNTDOWN_MS) { k -> sendSos(k) }
        startLocation()
        machine.startCountdown(SystemClock.elapsedRealtime())
        ticker.post(tick)
    }

    override fun onDestroy() {
        ticker.removeCallbacks(tick)
        if (!isChangingConfigurations) machine.cancel(SystemClock.elapsedRealtime()) // leaving sends nothing
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
        if (k == SosKind.REAL) openText()
        io.execute {
            val answer = try {
                if (!AppState(this).isLinked()) {
                    Answer(false, -1, NOT_LINKED)
                } else {
                    val reply = DoorClient(this).signed("sos", Payloads.sos(k, at, place))
                    if (reply.ok) Answer(true, reachedOf(reply.body), "") else Answer(false, -1, "refused")
                }
            } catch (e: IOException) {
                Answer(false, -1, "offline")
            } catch (e: GeneralSecurityException) {
                Answer(false, -1, "key")
            } catch (e: RuntimeException) {
                Answer(false, -1, "failed")
            }
            runOnUiThread { answered(k, answer) }
        }
    }

    private fun answered(k: SosKind, answer: Answer) {
        if (isFinishing || isDestroyed) return
        if (k == SosKind.SAFE) {
            status.setText(if (answer.ok) R.string.sos_safe_sent else R.string.sos_failed)
            return
        }
        machine.done(answer.ok, answer.reached, answer.why)
        render(SystemClock.elapsedRealtime())
    }

    private fun render(now: Long) {
        when (val s = machine.state) {
            is SosState.Counting -> {
                val left = machine.remainingSeconds(now)
                count.text = left.toString()
                val words = if (kind == SosKind.TEST) R.string.sos_counting_test else R.string.sos_counting
                status.text = getString(words, left.toInt())
                beep(left)
            }
            is SosState.Sending -> {
                count.text = ""
                status.setText(R.string.sos_sending)
                showAfter()
            }
            is SosState.Sent -> {
                status.text = if (s.reached >= 0) getString(R.string.sos_sent, s.reached) else getString(R.string.sos_sent_plain)
                showAfter()
            }
            is SosState.Failed -> {
                status.setText(if (s.why == NOT_LINKED) R.string.sos_not_linked else R.string.sos_failed)
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
        after.visibility = View.VISIBLE
        cancelButton.setText(R.string.sos_close)
    }

    private fun openText() {
        val saved = book
        val uri = saved?.let { b -> SosText.smsUri(b.contacts.map { it.phone }) }
        if (saved == null || uri == null) {
            where.text = getString(R.string.sos_no_numbers)
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
            status.setText(R.string.sos_failed)
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

        fun fromTile(context: Context): Intent =
            Intent(context, SosActivity::class.java).setAction(Launch.ACTION_PREFIX + "SOS")

        fun test(context: Context): Intent =
            Intent(context, SosActivity::class.java).putExtra(EXTRA_TEST, true)
    }
}

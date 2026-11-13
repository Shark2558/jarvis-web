// android/app/src/main/java/io/github/shark2558/jarvis/link/SetupActivity.kt
// R7 D5, D9, D10, D16, D17, D19, D21: the set-up screen. First the link: the 8-character code from
// Integrations -> Phone app -> Link a phone on the laptop (it needs the owner's passkey there);
// the phone makes its key in its secure hardware and sends only the public half. Then one line
// per choice, each asked only when the owner taps it: notifications, Health Connect's own
// permission screens, location for SOS (precise and approximate asked together, as Android
// requires), one folder, and the two tiles. Screenshots of this screen are blocked; it pads
// itself inside the system bars. While it is open it also reads the watch (the console is
// Chrome's window, which Health Connect counts as the background).
package io.github.shark2558.jarvis.link

import android.Manifest
import android.app.StatusBarManager
import android.content.ActivityNotFoundException
import android.content.ComponentName
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.drawable.Icon
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.app.NotificationManagerCompat
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.PermissionController
import io.github.shark2558.jarvis.R
import io.github.shark2558.jarvis.health.HealthAccess
import io.github.shark2558.jarvis.health.HealthPermissions
import io.github.shark2558.jarvis.health.HealthSync
import io.github.shark2558.jarvis.shell.Background
import io.github.shark2558.jarvis.shell.IconLauncherActivity
import io.github.shark2558.jarvis.shell.SosTileService
import io.github.shark2558.jarvis.shell.TalkTileService
import io.github.shark2558.jarvis.sos.SosActivity
import io.github.shark2558.jarvis.ui.Look
import io.github.shark2558.jarvis.ui.SystemBars
import java.io.IOException
import java.security.GeneralSecurityException
import java.text.DateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

class SetupActivity : ComponentActivity() {
    private val io: ExecutorService = Executors.newSingleThreadExecutor()
    private val state by lazy { AppState(this) }

    private val askNotifications =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { refresh() }
    private val askLocation =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { refresh() }
    private val askHealth =
        registerForActivityResult(PermissionController.createRequestPermissionResultContract()) {
            refresh()
            syncNow()
        }
    private val pickFolder =
        registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri -> if (uri != null) keepFolder(uri) }

    private lateinit var linkSection: View
    private lateinit var stepsSection: View
    private lateinit var codeField: EditText
    private lateinit var linkButton: Button
    private lateinit var linkStatus: TextView
    private lateinit var syncLine: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.setFlags(WindowManager.LayoutParams.FLAG_SECURE, WindowManager.LayoutParams.FLAG_SECURE)
        setContentView(R.layout.activity_setup)
        val root = findViewById<View>(R.id.setup_root)
        SystemBars.pad(this, root)
        Look.fonts(this, root)
        linkSection = findViewById(R.id.link_section)
        stepsSection = findViewById(R.id.steps_section)
        codeField = findViewById(R.id.link_code)
        linkButton = findViewById(R.id.link_button)
        linkStatus = findViewById(R.id.link_status)
        syncLine = findViewById(R.id.sync_line)
        linkButton.setOnClickListener { link() }
        button(R.id.do_notifications) { allowNotifications() }
        button(R.id.do_watch) { allowWatch() }
        button(R.id.do_sync) { syncNow() }
        button(R.id.do_location) {
            askLocation.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION))
        }
        button(R.id.do_folder) { pickFolder.launch(null) }
        button(R.id.do_tiles) { addTile(TalkTileService::class.java, R.string.tile_talk, R.drawable.ic_tile_talk) }
        button(R.id.do_tile_sos) { addTile(SosTileService::class.java, R.string.tile_sos, R.drawable.ic_tile_sos) }
        button(R.id.open_jarvis) {
            startActivity(Intent(this, IconLauncherActivity::class.java))
            finish()
        }
        button(R.id.test_sos) { startActivity(SosActivity.test(this)) }
    }

    override fun onResume() {
        super.onResume()
        refresh()
        if (state.isLinked()) helloAndSync()
    }

    override fun onDestroy() {
        io.shutdown()
        super.onDestroy()
    }

    private fun button(id: Int, action: () -> Unit) {
        findViewById<Button>(id).setOnClickListener { action() }
    }

    // ---- linking (D5) ------------------------------------------------------------------------
    private fun link() {
        val code = cleanCode(codeField.text?.toString().orEmpty())
        if (code == null) {
            linkStatus.setText(R.string.setup_code_bad)
            return
        }
        linkButton.isEnabled = false
        linkStatus.setText(R.string.setup_linking)
        io.execute {
            val failure = try {
                DoorClient(this).link(code)
                try {
                    Hello.send(this)
                } catch (e: Exception) {
                    // the link stands; "hello" is sent again when this screen or the job runs
                }
                0
            } catch (e: DoorRefused) {
                if (e.status in CLIENT_ERRORS) R.string.setup_link_refused else R.string.setup_link_failed
            } catch (e: IOException) {
                R.string.setup_link_offline
            } catch (e: GeneralSecurityException) {
                R.string.setup_link_failed
            } catch (e: Exception) {
                R.string.setup_link_failed
            }
            runOnUiThread {
                linkButton.isEnabled = true
                if (failure == 0) {
                    codeField.setText("")
                    linkStatus.text = ""
                    Background.schedule(this)
                    refresh()
                } else {
                    linkStatus.setText(failure)
                }
            }
        }
    }

    private fun cleanCode(typed: String): String? {
        val code = typed.uppercase(Locale.ROOT).filter { it != ' ' && it != '-' }
        return if (code.length == CODE_LENGTH && code.all { it in 'A'..'Z' || it in '0'..'9' }) code else null
    }

    // ---- the lines -----------------------------------------------------------------------------
    private fun refresh() {
        val linked = state.isLinked()
        linkSection.visibility = if (linked) View.GONE else View.VISIBLE
        stepsSection.visibility = if (linked) View.VISIBLE else View.GONE
        if (!linked) return
        line(R.id.state_notifications, if (notificationsOn()) R.string.state_on else R.string.state_off)
        line(R.id.state_location, if (locationOn()) R.string.state_on else R.string.state_off)
        line(R.id.state_folder, if (state.folder() != null) R.string.state_folder_on else R.string.state_off)
        val tiles = when {
            state.tileAdded() -> R.string.state_tile_added
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU -> R.string.state_off
            else -> R.string.state_tile_how
        }
        line(R.id.state_tiles, tiles)
        syncLine.text = syncText()
        refreshWatch()
    }

    private fun line(id: Int, words: Int) {
        findViewById<TextView>(id).setText(words)
    }

    private fun notificationsOn(): Boolean = NotificationManagerCompat.from(this).areNotificationsEnabled()

    private fun locationOn(): Boolean =
        checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED ||
            checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED

    private fun allowNotifications() {
        val firstAsk = !state.asked(NOTIFICATIONS)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU && firstAsk) {
            state.setAsked(NOTIFICATIONS)
            askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
            return
        }
        val settings = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, packageName)
        open(settings)
    }

    // ---- the watch (D17) -----------------------------------------------------------------------
    private fun refreshWatch() {
        val watchButton = findViewById<Button>(R.id.do_watch)
        when (HealthAccess.status(this)) {
            HealthConnectClient.SDK_AVAILABLE -> {
                watchButton.visibility = View.VISIBLE
                watchButton.setText(R.string.action_allow)
                io.execute {
                    val granted = try {
                        HealthAccess.granted(this)
                    } catch (e: Exception) {
                        emptySet()
                    }
                    val words = when {
                        granted.containsAll(HealthPermissions.ALL) -> R.string.state_on
                        granted.containsAll(HealthPermissions.READ) -> R.string.sync_background
                        granted.any { it in HealthPermissions.READ } -> R.string.state_partly
                        else -> R.string.state_off
                    }
                    runOnUiThread { line(R.id.state_watch, words) }
                }
            }
            HealthConnectClient.SDK_UNAVAILABLE_PROVIDER_UPDATE_REQUIRED -> {
                line(R.id.state_watch, R.string.state_hc_update)
                watchButton.setText(R.string.action_install_hc)
            }
            else -> {
                line(R.id.state_watch, R.string.state_no_hc)
                watchButton.visibility = View.GONE
            }
        }
    }

    private fun allowWatch() {
        when (HealthAccess.status(this)) {
            HealthConnectClient.SDK_AVAILABLE -> askHealth.launch(HealthPermissions.ALL)
            HealthConnectClient.SDK_UNAVAILABLE_PROVIDER_UPDATE_REQUIRED -> open(Intent(Intent.ACTION_VIEW, Uri.parse(HealthAccess.STORE)))
            else -> Unit
        }
    }

    private fun syncNow() {
        if (!state.isLinked()) return
        syncLine.setText(R.string.sync_running)
        io.execute {
            val outcome = try {
                HealthSync.run(this)
            } catch (e: Exception) {
                HealthSync.Outcome.FAILED
            }
            runOnUiThread { syncLine.text = getString(R.string.sync_outcome, getString(wordsFor(outcome)), syncText()) }
        }
    }

    private fun helloAndSync() {
        io.execute {
            try {
                Hello.send(this)
            } catch (e: Exception) {
                // the job sends it again later
            }
            val outcome = try {
                HealthSync.run(this)
            } catch (e: Exception) {
                HealthSync.Outcome.FAILED
            }
            runOnUiThread {
                if (!isFinishing && outcome == HealthSync.Outcome.SENT) syncLine.text = syncText()
            }
        }
    }

    private fun wordsFor(outcome: HealthSync.Outcome): Int = when (outcome) {
        HealthSync.Outcome.SENT -> R.string.sync_sent
        HealthSync.Outcome.NOTHING -> R.string.sync_nothing
        HealthSync.Outcome.NO_PERMISSION -> R.string.sync_no_permission
        HealthSync.Outcome.NO_HEALTH_CONNECT -> R.string.state_no_hc
        HealthSync.Outcome.NOT_LINKED, HealthSync.Outcome.FAILED -> R.string.sync_failed
    }

    private fun syncText(): String {
        val at = state.lastHealthSync()
        if (at == 0L) return getString(R.string.sync_never)
        val clock = DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(Date(at))
        return getString(R.string.sync_at, clock)
    }

    // ---- the folder (D16) and the tiles (D9) ----------------------------------------------------
    private fun keepFolder(tree: Uri) {
        try {
            contentResolver.takePersistableUriPermission(tree, Intent.FLAG_GRANT_READ_URI_PERMISSION)
        } catch (e: SecurityException) {
            return
        }
        state.setFolder(tree)
        Background.schedule(this)
        refresh()
    }

    private fun addTile(service: Class<*>, label: Int, icon: Int) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            line(R.id.state_tiles, R.string.state_tile_how)
            return
        }
        val bar = getSystemService(StatusBarManager::class.java) ?: return
        bar.requestAddTileService(
            ComponentName(this, service),
            getString(label),
            Icon.createWithResource(this, icon),
            mainExecutor,
        ) { _ -> runOnUiThread { refresh() } }
    }

    private fun open(intent: Intent) {
        try {
            startActivity(intent)
        } catch (e: ActivityNotFoundException) {
            linkStatus.setText(R.string.setup_link_failed)
        }
    }

    private companion object {
        const val CODE_LENGTH = 8
        const val NOTIFICATIONS = "notifications"
        val CLIENT_ERRORS = 400..499
    }
}

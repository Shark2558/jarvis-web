// android/app/src/main/java/io/github/shark2558/jarvis/link/Hello.kt
// R7 D6, D19: "hello" tells the server what the app may do (permission states, no values), and
// its answer carries, for the SMS screen, the owner's label and the SOS contacts' numbers, which
// the phone keeps encrypted with a key in its secure hardware (ContactsVault) so the text
// message works with no internet. Blocking: call it off the main thread.
package io.github.shark2558.jarvis.link

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationManagerCompat
import io.github.shark2558.jarvis.BuildConfig
import io.github.shark2558.jarvis.core.Payloads
import io.github.shark2558.jarvis.core.SosText
import io.github.shark2558.jarvis.health.HealthAccess
import io.github.shark2558.jarvis.health.HealthPermissions
import io.github.shark2558.jarvis.sos.ContactsVault
import org.json.JSONException
import org.json.JSONObject

data class SosContact(val label: String, val phone: String)

data class SosBook(val label: String, val contacts: List<SosContact>)

object Hello {
    private const val MAX_CONTACTS = 5

    fun send(context: Context): Boolean {
        val body = Payloads.hello(
            appVersion = BuildConfig.VERSION_NAME,
            versionCode = BuildConfig.VERSION_CODE,
            model = DoorClient.MODEL,
            android = Build.VERSION.SDK_INT,
            can = can(context),
        )
        val answer = DoorClient(context).signed("hello", body)
        if (!answer.ok) return false
        val book = parseBook(answer.body)
        if (book != null) ContactsVault.save(context, book)
        return true
    }

    fun can(context: Context): Payloads.Can {
        val health = HealthAccess.granted(context)
        val state = AppState(context)
        return Payloads.Can(
            notifications = NotificationManagerCompat.from(context).areNotificationsEnabled(),
            healthRead = health.containsAll(HealthPermissions.READ),
            healthBackground = HealthPermissions.BACKGROUND in health,
            location = granted(context, Manifest.permission.ACCESS_FINE_LOCATION) ||
                granted(context, Manifest.permission.ACCESS_COARSE_LOCATION),
            folder = state.folder() != null,
            tile = state.tileAdded(),
        )
    }

    /** The answer's SOS part: {"sos": {"label": "...", "contacts": [{"label": "...", "phone":
     *  "..."}]}}. Anything else is ignored; at most five contacts; numbers are cleaned. */
    fun parseBook(text: String): SosBook? {
        try {
            val sos = JSONObject(text).optJSONObject("sos") ?: return null
            val list = sos.optJSONArray("contacts")
            val contacts = ArrayList<SosContact>()
            if (list != null) {
                for (i in 0 until minOf(list.length(), MAX_CONTACTS)) {
                    val item = list.optJSONObject(i) ?: continue
                    val phone = SosText.cleanNumber(item.optString("phone", "")) ?: continue
                    contacts.add(SosContact(SosText.cleanLabel(item.optString("label", "")), phone))
                }
            }
            return SosBook(SosText.cleanLabel(sos.optString("label", "")), contacts)
        } catch (e: JSONException) {
            return null
        }
    }

    private fun granted(context: Context, permission: String): Boolean =
        context.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED
}

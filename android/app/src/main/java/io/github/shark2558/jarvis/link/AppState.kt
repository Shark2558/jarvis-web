// android/app/src/main/java/io/github/shark2558/jarvis/link/AppState.kt
// R7 D5, D16, D17: the little the app remembers, in its private preferences (never backed up:
// data_extraction_rules.xml): the device id the server gave at linking (public, not a secret:
// the key is in the phone's secure hardware), the folder the owner picked, the inbox's "seen"
// lists, which tiles are added and when the watch was last read. No session, no key, no value.
package io.github.shark2558.jarvis.link

import android.content.Context
import android.content.SharedPreferences
import android.net.Uri
import io.github.shark2558.jarvis.core.Door
import io.github.shark2558.jarvis.core.SeenList
import io.github.shark2558.jarvis.sos.ContactsVault

class AppState(context: Context) {
    private val appContext: Context = context.applicationContext
    private val prefs: SharedPreferences =
        context.applicationContext.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    fun deviceId(): String? = prefs.getString(DEVICE, null)?.takeIf { Door.isDeviceId(it) }

    fun isLinked(): Boolean = deviceId() != null

    fun saveDeviceId(id: String) {
        require(Door.isDeviceId(id)) { "not a device id" }
        prefs.edit().putString(DEVICE, id).remove(STRIKES).remove(RELINK).apply()
    }

    /** Forget this phone's link: the device id, the strikes and the sealed SOS contacts go. */
    fun forgetLink() {
        prefs.edit().remove(DEVICE).remove(STRIKES).remove(RELINK).apply()
        ContactsVault.clear(appContext)
    }

    /** Consecutive "this phone is not known" answers (see core's Replies.strikes). */
    fun strikes(): Int = prefs.getInt(STRIKES, 0)

    fun setStrikes(count: Int) {
        if (count != strikes()) prefs.edit().putInt(STRIKES, count).apply()
    }

    /** True once the door has refused this phone three times in a row: the jobs stop sending
     *  and the set-up screen asks for a new link code. Linking again clears it. */
    fun needsRelink(): Boolean = prefs.getBoolean(RELINK, false)

    fun setNeedsRelink(needed: Boolean) {
        if (needed != needsRelink()) prefs.edit().putBoolean(RELINK, needed).apply()
    }

    /** Linked and not refused: the jobs send only then. */
    fun canSend(): Boolean = isLinked() && !needsRelink()

    /** The folder's last plain-words note (a file the door refused for good, or a wait). */
    fun inboxNote(): String? = prefs.getString(INBOX_NOTE, null)

    fun setInboxNote(note: String?) {
        val editor = prefs.edit()
        if (note == null) editor.remove(INBOX_NOTE) else editor.putString(INBOX_NOTE, note)
        editor.apply()
    }

    /** The id of the last SOS press that started its send (so a recreated screen cannot send it
     *  again, even after the process was restarted). */
    fun lastSosPress(): String? = prefs.getString(SOS_PRESS, null)

    fun setLastSosPress(id: String) {
        prefs.edit().putString(SOS_PRESS, id).commit()
    }

    fun tileAdded(): Boolean = prefs.getBoolean(TILE_PREFIX + TILE_TALK, false) ||
        prefs.getBoolean(TILE_PREFIX + TILE_SOS, false)

    fun setTile(name: String, added: Boolean) {
        prefs.edit().putBoolean(TILE_PREFIX + name, added).apply()
    }

    fun folder(): Uri? = prefs.getString(FOLDER, null)?.let { Uri.parse(it) }

    fun setFolder(uri: Uri?) {
        val editor = prefs.edit()
        if (uri == null) editor.remove(FOLDER) else editor.putString(FOLDER, uri.toString())
        editor.apply()
    }

    fun seen(): SeenList = SeenList.decode(prefs.getString(SEEN, null))

    fun saveSeen(list: SeenList) {
        prefs.edit().putString(SEEN, list.encode()).apply()
    }

    fun seenKeys(): SeenList = SeenList.decode(prefs.getString(SEEN_KEYS, null))

    fun saveSeenKeys(list: SeenList) {
        prefs.edit().putString(SEEN_KEYS, list.encode()).apply()
    }

    fun lastHealthSync(): Long = prefs.getLong(HEALTH_AT, 0L)

    fun setLastHealthSync(at: Long) {
        prefs.edit().putLong(HEALTH_AT, at).apply()
    }

    fun asked(what: String): Boolean = prefs.getBoolean(ASKED_PREFIX + what, false)

    fun setAsked(what: String) {
        prefs.edit().putBoolean(ASKED_PREFIX + what, true).apply()
    }

    companion object {
        const val TILE_TALK = "talk"
        const val TILE_SOS = "sos"
        private const val FILE = "jarvis_app"
        private const val DEVICE = "device_id"
        private const val TILE_PREFIX = "tile_"
        private const val FOLDER = "folder"
        private const val SEEN = "inbox_seen"
        private const val SEEN_KEYS = "inbox_seen_keys"
        private const val HEALTH_AT = "health_at"
        private const val ASKED_PREFIX = "asked_"
        private const val STRIKES = "link_strikes"
        private const val RELINK = "needs_relink"
        private const val INBOX_NOTE = "inbox_note"
        private const val SOS_PRESS = "sos_last_press"
    }
}

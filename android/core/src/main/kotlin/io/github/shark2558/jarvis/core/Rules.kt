// android/core/src/main/kotlin/io/github/shark2558/jarvis/core/Rules.kt
// R7 D8, D10, D16: the launch words (a launch address opens a screen and never acts), the
// notification channel picked by an alert's tag, and the inbox's "seen" list and file rules.
package io.github.shark2558.jarvis.core

import java.util.Locale

object Launch {
    /** phone-contract.md section 5: exactly four words. */
    val WORDS: List<String> = listOf("talk", "look", "sos", "shared")
    const val ACTION_PREFIX = "io.github.shark2558.jarvis.action."
    private val LABEL = Regex("[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
    private const val MAX_HOST = 253

    /** The icon's launcher always opens this address and ignores any address an intent carries. */
    fun iconUrl(host: String): String = "https://${checkedHost(host)}/?source=app"

    /** The tile and the shortcuts (the second launcher, which other apps cannot start) add ONE
     *  word from the allow-list; anything else opens the icon's address. */
    fun screenUrl(host: String, word: String?): String =
        if (word != null && word in WORDS) "${iconUrl(host)}&do=$word" else iconUrl(host)

    /** This app's own actions (…action.TALK, …action.LOOK, …action.SOS) name a word. */
    fun wordForAction(action: String?): String? {
        if (action == null || !action.startsWith(ACTION_PREFIX)) return null
        val word = action.substring(ACTION_PREFIX.length).lowercase(Locale.ROOT)
        return if (word in WORDS) word else null
    }

    /** A plain lowercase host name: no scheme, port, path or space, and not an IP address. */
    fun isHost(host: String): Boolean {
        if (host.isEmpty() || host.length > MAX_HOST) return false
        val labels = host.split('.')
        if (labels.size < 2 || !labels.all { LABEL.matches(it) }) return false
        return !labels.last().all { it.isDigit() }
    }

    fun checkedHost(host: String): String {
        require(isHost(host)) { "the JARVIS address must be a host name such as jarvis.example.com" }
        return host
    }
}

enum class AlertChannel(val id: String) {
    URGENT("jarvis_urgent"),
    ALERTS("jarvis_alerts"),
    NUDGES("jarvis_nudges"),
}

object Channels {
    /** phone-contract.md section 6. */
    val URGENT_KINDS: Set<String> = setOf("home_intruder", "home_hazard", "disaster_alert", "sos_sent", "phone_linked")
    private val KIND = Regex("[a-z][a-z0-9_]{0,63}")

    /** The alert's kind from the notification's tag. The push worker sets `tag: kind`; Chrome's
     *  own tag form is not documented, so the kind is read from after its last '#', without the
     *  '1' Chrome may put before a site's own tag. Anything else is unreadable (null). */
    fun kindFromTag(tag: String?): String? {
        if (tag == null) return null
        var last = tag.substringAfterLast('#')
        if (last != tag && last.startsWith("1")) last = last.substring(1)
        return if (KIND.matches(last)) last else null
    }

    fun forTag(tag: String?): AlertChannel {
        val kind = kindFromTag(tag) ?: return AlertChannel.ALERTS
        return when {
            kind in URGENT_KINDS -> AlertChannel.URGENT
            kind.startsWith("nudge_") -> AlertChannel.NUDGES
            else -> AlertChannel.ALERTS
        }
    }
}

/** The inbox's memory of files already sent, by SHA-256 (D16: each file once). */
class SeenList private constructor(private val items: List<String>, private val cap: Int) {
    val size: Int get() = items.size

    operator fun contains(sha256: String): Boolean = sha256 in items

    fun adding(sha256: String): SeenList =
        if (sha256 in items || !SHA.matches(sha256)) this else SeenList((items + sha256).takeLast(cap), cap)

    fun encode(): String = items.joinToString("\n")

    companion object {
        const val CAP = 1000
        private val SHA = Regex("[0-9a-f]{64}")

        fun decode(text: String?, cap: Int = CAP): SeenList {
            val items = text.orEmpty().lineSequence().map { it.trim() }.filter { SHA.matches(it) }.distinct().toList()
            return SeenList(items.takeLast(cap), cap)
        }
    }
}

object InboxRules {
    const val MAX_BYTES: Long = 10L * 1024L * 1024L
    const val PER_RUN = 3
    private const val MAX_NAME = 120
    val MIMES: Set<String> = setOf("application/pdf", "image/jpeg", "image/png")

    data class Candidate(val id: String, val name: String, val mime: String, val size: Long, val modifiedMs: Long)

    fun eligible(c: Candidate): Boolean = c.mime in MIMES && c.size in 1L..MAX_BYTES

    /** The files worth reading, oldest first. */
    fun order(candidates: List<Candidate>): List<Candidate> =
        candidates.filter { eligible(it) }.sortedWith(compareBy<Candidate>({ it.modifiedMs }, { it.name }, { it.id }))

    /** The type from the file's own first bytes (a name or a provider's word can lie). */
    fun sniff(head: ByteArray): String? = when {
        starts(head, byteArrayOf(0x25, 0x50, 0x44, 0x46, 0x2D)) -> "application/pdf"
        starts(head, byteArrayOf(0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A)) -> "image/png"
        starts(head, byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 0xFF.toByte())) -> "image/jpeg"
        else -> null
    }

    /** No folders, no control characters, at most 120 characters. */
    fun cleanName(name: String): String {
        val base = name.substringAfterLast('/').substringAfterLast('\\')
        val clean = base.filter { !it.isISOControl() }.trim().take(MAX_NAME)
        return clean.ifEmpty { "document" }
    }

    private fun starts(head: ByteArray, magic: ByteArray): Boolean =
        head.size >= magic.size && head.copyOfRange(0, magic.size).contentEquals(magic)
}

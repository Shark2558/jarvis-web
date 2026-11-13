// android/core/src/main/kotlin/io/github/shark2558/jarvis/core/Replies.kt
// R7 D6, D16: what the door's answers mean, in plain words, and what the app does about each.
// Pure, so a JVM test holds it: 401 (with a hint that the phone's clock may be off when the
// server's `Date` differs by more than 120 seconds), 403, 404, 413, 429 and 5xx each get their
// own sentence; the jobs retry only 408, 425, 429 and 5xx (and network errors); the folder marks
// a file handled only on success or a permanent refusal; after three 401s in a row the app says
// "This phone needs linking again, Sir" and stops sending (it never forgets the link silently).
package io.github.shark2558.jarvis.core

import kotlin.math.abs

enum class Refusal(val sentence: String) {
    UNKNOWN_PHONE("JARVIS did not recognise this phone, Sir. If this goes on it will ask to be linked again."),
    CLOCK("The phone's clock looks wrong, Sir. Please set Date and time to automatic, then try again."),
    FORBIDDEN("JARVIS refused this request, Sir. Linking the phone again usually puts it right."),
    NOT_FOUND("JARVIS does not know this request yet, Sir. The app may be newer than JARVIS."),
    TOO_BIG("That was too big for JARVIS to take, Sir."),
    TOO_MANY("Too many tries at once, Sir. Please wait a minute."),
    BUSY("JARVIS is busy at the moment, Sir. It will try again later."),
    SERVER("JARVIS had a problem on its side, Sir. It will try again later."),
    REJECTED("JARVIS did not accept that, Sir."),
}

object Replies {
    /** The door refuses a signature older or newer than this (phone-contract.md). */
    const val MAX_SKEW_SECONDS = 120L
    const val NEEDS_LINKING = "This phone needs linking again, Sir."
    const val UNREACHED = "JARVIS could not be reached, Sir. It will try again later."

    private const val OK_FROM = 200
    private const val OK_TO = 299

    /** Whole seconds the server's clock is ahead of the phone's (negative: behind); null when
     *  the answer carried no usable `Date`. */
    fun skewSeconds(phoneMs: Long, serverMs: Long): Long? =
        if (serverMs <= 0L) null else (serverMs - phoneMs) / 1000L

    /** The refusal behind a status, or null for a 2xx. */
    fun explain(status: Int, skewSeconds: Long?): Refusal? = when {
        status in OK_FROM..OK_TO -> null
        status == 401 && skewSeconds != null && abs(skewSeconds) > MAX_SKEW_SECONDS -> Refusal.CLOCK
        status == 401 -> Refusal.UNKNOWN_PHONE
        status == 403 -> Refusal.FORBIDDEN
        status == 404 -> Refusal.NOT_FOUND
        status == 413 -> Refusal.TOO_BIG
        status == 429 -> Refusal.TOO_MANY
        status == 408 || status == 425 -> Refusal.BUSY
        status >= 500 -> Refusal.SERVER
        else -> Refusal.REJECTED
    }

    /** A job tries again later only for these (and for network errors); any other 4xx will not
     *  change by waiting. */
    fun worthRetry(status: Int): Boolean = status == 408 || status == 425 || status == 429 || status >= 500

    /** The unlinking rule: consecutive "this phone is not known" answers. A clock fault does not
     *  count (the phone is fine), nor does any other refusal; a 2xx starts again from zero. */
    const val RELINK_AFTER = 3

    fun strikes(before: Int, refusal: Refusal?): Int = when (refusal) {
        null -> 0
        Refusal.UNKNOWN_PHONE -> before + 1
        else -> before
    }

    fun needsLinking(strikes: Int): Boolean = strikes >= RELINK_AFTER
}

/** What the folder does with a file after the door's answer. */
enum class InboxFate { SENT, REFUSED_FOR_GOOD, LATER }

object Inbox {
    private val FOR_GOOD = setOf(400, 413, 415, 422)

    /** Success, or a refusal that waiting will not change (the file itself is the problem):
     *  the file is marked handled. Everything else, 401, 403, 404, 408, 425, 429 and 5xx, leaves
     *  it unmarked for the next run. */
    fun fate(status: Int): InboxFate = when {
        status in 200..299 -> InboxFate.SENT
        status in FOR_GOOD -> InboxFate.REFUSED_FOR_GOOD
        else -> InboxFate.LATER
    }
}

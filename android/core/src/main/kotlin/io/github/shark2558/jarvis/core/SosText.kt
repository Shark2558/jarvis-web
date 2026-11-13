// android/core/src/main/kotlin/io/github/shark2558/jarvis/core/SosText.kt
// R7 D19: the text message the phone's own SMS app opens with, for the owner to press Send. Code,
// never a model: one fixed sentence, the location as a map link with how accurate it is, or
// "not available". The coordinates are used once, here, and never stored or logged.
package io.github.shark2558.jarvis.core

import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlin.math.abs

object SosText {
    private const val MAX_LABEL = 40
    private const val E6 = 1_000_000L
    private val NUMBER = Regex("\\+?[0-9]{3,15}")
    private val CLOCK: DateTimeFormatter = DateTimeFormatter.ofPattern("HH:mm", Locale.ROOT)

    fun message(label: String?, fix: Fix?, zone: ZoneId): String {
        val who = cleanLabel(label)
        val head = if (who.isEmpty()) "SOS: I need help." else "SOS from $who: I need help."
        val where = if (fix == null) {
            "My location is not available."
        } else {
            "My location at ${clock(fix.atEpochS, zone)}: ${mapsLink(fix)} (within about ${fix.accuracyM} m)."
        }
        return "$head $where Sent by my JARVIS assistant."
    }

    fun mapsLink(fix: Fix): String = "https://maps.google.com/?q=${degrees(fix.latE6)},${degrees(fix.lonE6)}"

    /** Micro-degrees as degrees with six decimals, by integer arithmetic (no locale). */
    fun degrees(e6: Long): String {
        val sign = if (e6 < 0) "-" else ""
        val a = abs(e6)
        return sign + (a / E6).toString() + "." + (a % E6).toString().padStart(6, '0')
    }

    fun cleanLabel(label: String?): String = label.orEmpty().filter { !it.isISOControl() }.trim().take(MAX_LABEL)

    fun cleanNumber(number: String): String? {
        val kept = number.filter { it.isDigit() || it == '+' }
        return if (NUMBER.matches(kept)) kept else null
    }

    /** `smsto:` with every usable number once, or null when there is none. */
    fun smsUri(numbers: List<String>): String? {
        val clean = numbers.mapNotNull { cleanNumber(it) }.distinct()
        return if (clean.isEmpty()) null else "smsto:" + clean.joinToString(";")
    }

    private fun clock(epochS: Long, zone: ZoneId): String = CLOCK.format(Instant.ofEpochSecond(epochS).atZone(zone))
}

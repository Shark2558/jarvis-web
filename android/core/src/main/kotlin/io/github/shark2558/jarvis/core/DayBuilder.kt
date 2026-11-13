// android/core/src/main/kotlin/io/github/shark2558/jarvis/core/DayBuilder.kt
// R7 D17: the Health Connect day builder. Three apps can write the same steps on the owner's phone
// (NoiseFit, the phone itself, Google Fit), so:
//  - steps and heart rate come ONLY from Health Connect's own `aggregate`, which removes duplicates
//    by the owner's App priority list (owner step A2: NoiseFit first). `HealthSource` offers no raw
//    step records at all, so nothing here can add them up;
//  - sleep comes as sessions, and the builder keeps ONE writer for each night: sessions that
//    overlap are one night, and the watch is kept before the phone, any other app after both.
// Each kept writer is named by kind (watch, phone, other); the body carries its package name.
package io.github.shark2558.jarvis.core

import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.Locale

enum class StageKind { AWAKE, LIGHT, DEEP, REM, OTHER }

data class StageSpan(val startEpochS: Long, val endEpochS: Long, val kind: StageKind)

/** One sleep session as Health Connect wrote it (times in epoch seconds, offsets in seconds). */
data class SleepRecord(
    val startEpochS: Long,
    val startOffsetS: Int,
    val endEpochS: Long,
    val endOffsetS: Int,
    val writer: String,
    val stages: List<StageSpan>,
)

/** A total from Health Connect's `aggregate`, with the apps that wrote it. */
data class Aggregate(val count: Long, val origins: Set<String>)

data class HeartAggregate(val min: Long, val avg: Long, val max: Long, val origins: Set<String>)

/** What the reader asks Health Connect for. There is deliberately no way to read raw step or
 *  heart-rate records: totals come from the aggregate, which removes duplicates. */
interface HealthSource {
    fun steps(start: Instant, end: Instant): Aggregate?

    fun heart(start: Instant, end: Instant): HeartAggregate?

    fun sleep(start: Instant, end: Instant): List<SleepRecord>
}

enum class WriterKind(val word: String, val rank: Int) {
    WATCH("watch", 0),
    PHONE("phone", 1),
    OTHER("other", 2),
}

/** Which writer is the watch and which is the phone. The app passes `isPhone` so that a system
 *  app of the phone (its maker's health service) counts as the phone. */
class Writers(
    private val watchApps: Set<String> = WATCH_APPS,
    private val isPhone: (String) -> Boolean = { it in PHONE_APPS },
) {
    fun kind(writer: String): WriterKind = when {
        writer in watchApps -> WriterKind.WATCH
        isPhone(writer) -> WriterKind.PHONE
        else -> WriterKind.OTHER
    }

    /** The writer to name for a total: the watch first, then the phone, then by name. */
    fun best(origins: Collection<String>): String? =
        origins.minWithOrNull(compareBy<String>({ kind(it).rank }, { it }))

    companion object {
        val WATCH_APPS: Set<String> = setOf("com.noisefit")
        val PHONE_APPS: Set<String> = setOf("android")
        const val UNKNOWN = "unknown"
    }
}

class DayBuilder(private val zone: ZoneId, private val writers: Writers = Writers()) {
    fun build(source: HealthSource, days: List<LocalDate>): List<HealthDay> {
        require(days.size <= Payloads.MAX_DAYS) { "at most ${Payloads.MAX_DAYS} days" }
        val sorted = days.distinct().sorted()
        if (sorted.isEmpty()) return emptyList()
        // a night that ends on the first day began the evening before it
        val from = startOf(sorted.first()).minusSeconds(DAY_S)
        val to = startOf(sorted.last().plusDays(1))
        val kept = keepOneWriter(source.sleep(from, to))
        return sorted.map { date ->
            val start = startOf(date)
            val end = startOf(date.plusDays(1))
            HealthDay(
                date = date.toString(),
                steps = source.steps(start, end)?.takeIf { it.count > 0 }?.let {
                    StepsDay(it.count, writers.best(it.origins) ?: Writers.UNKNOWN)
                },
                heart = source.heart(start, end)?.let {
                    HeartDay(it.min, it.avg, it.max, writers.best(it.origins) ?: Writers.UNKNOWN)
                },
                sleep = kept.filter { endDate(it) == date }.sortedBy { it.startEpochS }.map { session(it) },
            )
        }
    }

    /** Sessions that overlap are one night; each night keeps one writer's sessions. */
    fun keepOneWriter(records: List<SleepRecord>): List<SleepRecord> {
        val valid = records
            .filter { it.endEpochS > it.startEpochS }
            .sortedWith(compareBy<SleepRecord>({ it.startEpochS }, { it.endEpochS }, { it.writer }))
        val kept = ArrayList<SleepRecord>()
        var night = ArrayList<SleepRecord>()
        var nightEnd = Long.MIN_VALUE
        for (r in valid) {
            if (night.isNotEmpty() && r.startEpochS >= nightEnd) {
                kept.addAll(oneWriter(night))
                night = ArrayList()
                nightEnd = Long.MIN_VALUE
            }
            night.add(r)
            nightEnd = maxOf(nightEnd, r.endEpochS)
        }
        if (night.isNotEmpty()) kept.addAll(oneWriter(night))
        return kept
    }

    private fun oneWriter(night: List<SleepRecord>): List<SleepRecord> {
        val writer = night.map { it.writer }.distinct().minWith(
            compareBy<String>({ writers.kind(it).rank }, { -secondsOf(night, it) }, { it }),
        )
        return night.filter { it.writer == writer }
    }

    private fun secondsOf(night: List<SleepRecord>, writer: String): Long =
        night.filter { it.writer == writer }.sumOf { it.endEpochS - it.startEpochS }

    private fun session(r: SleepRecord): SleepSession = SleepSession(
        start = iso(r.startEpochS, r.startOffsetS),
        end = iso(r.endEpochS, r.endOffsetS),
        writer = r.writer,
        stages = stages(r.stages),
    )

    private fun stages(spans: List<StageSpan>): Stages? {
        val staged = spans.any { it.kind == StageKind.LIGHT || it.kind == StageKind.DEEP || it.kind == StageKind.REM }
        if (!staged) return null
        return Stages(
            awake = minutes(spans, StageKind.AWAKE),
            light = minutes(spans, StageKind.LIGHT),
            deep = minutes(spans, StageKind.DEEP),
            rem = minutes(spans, StageKind.REM),
        )
    }

    private fun minutes(spans: List<StageSpan>, kind: StageKind): Long =
        spans.filter { it.kind == kind }.sumOf { maxOf(0L, it.endEpochS - it.startEpochS) } / 60L

    private fun startOf(date: LocalDate): Instant = date.atStartOfDay(zone).toInstant()

    private fun endDate(r: SleepRecord): LocalDate =
        Instant.ofEpochSecond(r.endEpochS).atOffset(ZoneOffset.ofTotalSeconds(r.endOffsetS)).toLocalDate()

    private fun iso(epochS: Long, offsetS: Int): String =
        ISO.format(Instant.ofEpochSecond(epochS).atOffset(ZoneOffset.ofTotalSeconds(offsetS)))

    private companion object {
        const val DAY_S = 86_400L
        val ISO: DateTimeFormatter = DateTimeFormatter.ofPattern("uuuu-MM-dd'T'HH:mm:ssxxx", Locale.ROOT)
    }
}

// android/core/src/test/kotlin/io/github/shark2558/jarvis/core/DayBuilderTest.kt
// R7 D17, D24: the Health Connect day builder. Musts: two writers on one night keep NoiseFit's;
// the phone alone is kept and named "phone"; three steps writers give ONE count, because steps
// come from Health Connect's own `aggregate` (which removes duplicates by App priority), never
// from a sum of raw records. The fake client below holds the raw records of three writers.
package io.github.shark2558.jarvis.core

import java.time.Instant
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneId

private val KOLKATA: ZoneId = ZoneId.of("Asia/Kolkata")
private const val IST_S = 19_800 // +05:30
private const val NOISEFIT = "com.noisefit"
private const val PHONE = "android"
private const val FIT = "com.google.android.apps.fitness"
private val DAY: LocalDate = LocalDate.parse("2026-11-12")

private fun at(text: String): Long = OffsetDateTime.parse(text).toEpochSecond()

private fun night(writer: String, start: String, end: String, stages: List<StageSpan> = emptyList()) =
    SleepRecord(at(start), IST_S, at(end), IST_S, writer, stages)

private fun watchStages(): List<StageSpan> = listOf(
    StageSpan(at("2026-11-11T23:50:00+05:30"), at("2026-11-12T03:20:00+05:30"), StageKind.LIGHT),
    StageSpan(at("2026-11-12T03:20:00+05:30"), at("2026-11-12T04:40:00+05:30"), StageKind.DEEP),
    StageSpan(at("2026-11-12T04:40:00+05:30"), at("2026-11-12T06:18:00+05:30"), StageKind.REM),
    StageSpan(at("2026-11-12T06:18:00+05:30"), at("2026-11-12T06:30:00+05:30"), StageKind.AWAKE),
)

/** A stand-in for Health Connect with three writers. Its `steps` answers as Health Connect's
 *  `aggregate` does with App priority set (NoiseFit first): the same walk written three times
 *  counts once, by the first writer in the priority list that has data. */
private class FakeHealth(
    private val rawSteps: List<Pair<String, Long>>,
    private val heart: HeartAggregate? = null,
    private val sessions: List<SleepRecord> = emptyList(),
    private val priority: List<String> = listOf(NOISEFIT, PHONE, FIT),
) : HealthSource {
    val asked = ArrayList<String>()

    fun rawSum(): Long = rawSteps.sumOf { it.second }

    override fun steps(start: Instant, end: Instant): Aggregate? {
        asked.add("steps")
        val writers = rawSteps.map { it.first }.toSet()
        val top = priority.firstOrNull { it in writers } ?: return null
        return Aggregate(rawSteps.filter { it.first == top }.sumOf { it.second }, setOf(top))
    }

    override fun heart(start: Instant, end: Instant): HeartAggregate? {
        asked.add("heart")
        return heart
    }

    override fun sleep(start: Instant, end: Instant): List<SleepRecord> {
        asked.add("sleep")
        return sessions.filter { it.endEpochS > start.epochSecond && it.startEpochS < end.epochSecond }
    }
}

private fun build(fake: HealthSource, vararg days: LocalDate): List<HealthDay> =
    DayBuilder(KOLKATA).build(fake, days.toList())

fun dayCases(): List<Case> = cases(
    "day",
    "three steps writers give one count, from the aggregate, never the raw sum" to {
        val fake = FakeHealth(listOf(NOISEFIT to 8123L, PHONE to 7990L, FIT to 8001L))
        val day = build(fake, DAY).single()
        same(8123L, day.steps?.count, "steps counted once")
        same(NOISEFIT, day.steps?.writer, "the watch's count is kept")
        yes(fake.rawSum() == 24_114L && day.steps?.count != fake.rawSum(), "the raw records are not summed")
        yes("steps" in fake.asked, "steps were asked from the aggregate")
    },
    "two writers on one night keep NoiseFit's" to {
        val watch = night(NOISEFIT, "2026-11-11T23:50:00+05:30", "2026-11-12T06:30:00+05:30", watchStages())
        val phone = night(PHONE, "2026-11-11T23:30:00+05:30", "2026-11-12T06:45:00+05:30")
        val day = build(FakeHealth(emptyList(), sessions = listOf(phone, watch)), DAY).single()
        same(1, day.sleep.size, "one session kept for the night")
        val kept = day.sleep.single()
        same(NOISEFIT, kept.writer, "the watch's night is kept")
        same("2026-11-11T23:50:00+05:30", kept.start, "start with its offset")
        same("2026-11-12T06:30:00+05:30", kept.end, "end with its offset")
        same(Stages(awake = 12, light = 210, deep = 80, rem = 98), kept.stages, "minutes per stage")
        same(WriterKind.WATCH, Writers().kind(kept.writer), "named as the watch")
    },
    "the phone alone is kept and named \"phone\"" to {
        val phone = night(PHONE, "2026-11-11T23:30:00+05:30", "2026-11-12T06:45:00+05:30")
        val day = build(FakeHealth(emptyList(), sessions = listOf(phone)), DAY).single()
        val kept = day.sleep.single()
        same(PHONE, kept.writer, "the phone's package is the writer")
        same("phone", Writers().kind(kept.writer).word, "named phone")
        same(null, kept.stages, "no stages when the writer wrote none")
    },
    "the phone comes before any other app, and another app alone is kept" to {
        val fit = night(FIT, "2026-11-11T23:40:00+05:30", "2026-11-12T06:40:00+05:30")
        val phone = night(PHONE, "2026-11-11T23:30:00+05:30", "2026-11-12T06:45:00+05:30")
        same(PHONE, build(FakeHealth(emptyList(), sessions = listOf(fit, phone)), DAY).single().sleep.single().writer, "phone over another app")
        val alone = build(FakeHealth(emptyList(), sessions = listOf(fit)), DAY).single().sleep.single()
        same(FIT, alone.writer, "another app alone is kept")
        same(WriterKind.OTHER, Writers().kind(alone.writer), "named other")
    },
    "a nap that overlaps nothing is kept beside the night" to {
        val nap = night(NOISEFIT, "2026-11-12T14:00:00+05:30", "2026-11-12T14:30:00+05:30")
        val phone = night(PHONE, "2026-11-11T23:30:00+05:30", "2026-11-12T06:45:00+05:30")
        val sleep = build(FakeHealth(emptyList(), sessions = listOf(nap, phone)), DAY).single().sleep
        same(listOf(PHONE, NOISEFIT), sleep.map { it.writer }, "night and nap, in time order")
    },
    "a night belongs to the day it ends on" to {
        val phone = night(PHONE, "2026-11-11T23:30:00+05:30", "2026-11-12T06:45:00+05:30")
        val days = build(FakeHealth(emptyList(), sessions = listOf(phone)), DAY.minusDays(1), DAY)
        same(listOf("2026-11-11", "2026-11-12"), days.map { it.date }, "two days in order")
        same(0, days[0].sleep.size, "nothing on the day before")
        same(1, days[1].sleep.size, "the night on the day it ended")
    },
    "heart rate is the aggregate's lowest, average and highest, by the best writer" to {
        val fake = FakeHealth(emptyList(), heart = HeartAggregate(58, 74, 131, setOf(PHONE, NOISEFIT)))
        same(HeartDay(58, 74, 131, NOISEFIT), build(fake, DAY).single().heart, "heart")
        same(null, build(FakeHealth(emptyList()), DAY).single().heart, "no heart rate: null")
    },
    "a day with no steps has null steps, not zero" to {
        same(null, build(FakeHealth(emptyList()), DAY).single().steps, "no steps")
        same(null, build(FakeHealth(listOf(PHONE to 0L)), DAY).single().steps, "zero steps")
    },
    "at most 35 days are built" to {
        val days = (0L until 36L).map { DAY.minusDays(it) }
        refuses<IllegalArgumentException>("36 days") { DayBuilder(KOLKATA).build(FakeHealth(emptyList()), days) }
        same(35, DayBuilder(KOLKATA).build(FakeHealth(emptyList()), days.take(35)).size, "35 days")
    },
    "the built days are the contract's health body" to {
        val watch = night(NOISEFIT, "2026-11-11T23:50:00+05:30", "2026-11-12T06:30:00+05:30", watchStages())
        val fake = FakeHealth(listOf(NOISEFIT to 8123L), HeartAggregate(58, 74, 131, setOf(NOISEFIT)), listOf(watch))
        val body = String(Payloads.health(build(fake, DAY)), Charsets.UTF_8)
        val expected = "{\"v\":1,\"days\":[{\"date\":\"2026-11-12\",\"steps\":{\"count\":8123,\"writer\":\"com.noisefit\"}," +
            "\"heart\":{\"min\":58,\"avg\":74,\"max\":131,\"writer\":\"com.noisefit\"},\"sleep\":[{\"start\":" +
            "\"2026-11-11T23:50:00+05:30\",\"end\":\"2026-11-12T06:30:00+05:30\",\"writer\":\"com.noisefit\"," +
            "\"stages\":{\"awake\":12,\"light\":210,\"deep\":80,\"rem\":98}}]}]}"
        same(expected, body, "health body")
    },
    "a system app of the phone counts as the phone" to {
        val writers = Writers(isPhone = { it == PHONE || it == "com.example.phonehealth" })
        same(WriterKind.PHONE, writers.kind("com.example.phonehealth"), "a system app is the phone")
        same(NOISEFIT, writers.best(setOf("com.example.phonehealth", NOISEFIT)), "the watch still wins")
        same(null, writers.best(emptySet()), "no writer")
    },
    "a session that ends before it starts is dropped" to {
        val bad = SleepRecord(at("2026-11-12T06:00:00+05:30"), IST_S, at("2026-11-12T05:00:00+05:30"), IST_S, PHONE, emptyList())
        same(0, build(FakeHealth(emptyList(), sessions = listOf(bad)), DAY).single().sleep.size, "dropped")
    },
)

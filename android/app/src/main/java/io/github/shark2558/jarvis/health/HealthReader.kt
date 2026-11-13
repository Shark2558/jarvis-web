// android/app/src/main/java/io/github/shark2558/jarvis/health/HealthReader.kt
// R7 D17: core's HealthSource over Health Connect. Steps and heart rate are read ONLY with
// Health Connect's own `aggregate`, which removes duplicates by the owner's App priority list
// (NoiseFit first, owner step A2): the phone, Google Fit and NoiseFit can all write the same
// walk, and a sum of raw records would count it two or three times. Sleep is read as sessions;
// core's DayBuilder keeps one writer for each night. Kinds the owner did not allow are skipped.
package io.github.shark2558.jarvis.health

import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.aggregate.AggregationResult
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.request.AggregateRequest
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import io.github.shark2558.jarvis.core.Aggregate
import io.github.shark2558.jarvis.core.HealthSource
import io.github.shark2558.jarvis.core.HeartAggregate
import io.github.shark2558.jarvis.core.SleepRecord
import io.github.shark2558.jarvis.core.StageKind
import io.github.shark2558.jarvis.core.StageSpan
import java.time.Instant
import java.time.ZoneId

class HealthReader(
    private val client: HealthConnectClient,
    private val zone: ZoneId,
    private val granted: Set<String>,
) : HealthSource {
    override fun steps(start: Instant, end: Instant): Aggregate? {
        if (HealthPermissions.STEPS !in granted) return null
        val result = await {
            client.aggregate(AggregateRequest(setOf(StepsRecord.COUNT_TOTAL), TimeRangeFilter.between(start, end)))
        }
        val count = result[StepsRecord.COUNT_TOTAL] ?: return null
        return Aggregate(count, originsOf(result))
    }

    override fun heart(start: Instant, end: Instant): HeartAggregate? {
        if (HealthPermissions.HEART !in granted) return null
        val metrics = setOf(HeartRateRecord.BPM_MIN, HeartRateRecord.BPM_AVG, HeartRateRecord.BPM_MAX)
        val result = await { client.aggregate(AggregateRequest(metrics, TimeRangeFilter.between(start, end))) }
        val min = result[HeartRateRecord.BPM_MIN] ?: return null
        val avg = result[HeartRateRecord.BPM_AVG] ?: return null
        val max = result[HeartRateRecord.BPM_MAX] ?: return null
        return HeartAggregate(min, avg, max, originsOf(result))
    }

    override fun sleep(start: Instant, end: Instant): List<SleepRecord> {
        if (HealthPermissions.SLEEP !in granted) return emptyList()
        val out = ArrayList<SleepRecord>()
        var token: String? = null
        var pages = 0
        do {
            val request = ReadRecordsRequest(
                SleepSessionRecord::class,
                TimeRangeFilter.between(start, end),
                pageToken = token,
            )
            val page = await { client.readRecords(request) }
            for (record in page.records) out.add(toCore(record))
            token = page.pageToken
            pages += 1
        } while (token != null && pages < MAX_PAGES)
        return out
    }

    private fun originsOf(result: AggregationResult): Set<String> =
        result.dataOrigins.map { it.packageName }.toSet()

    private fun toCore(r: SleepSessionRecord): SleepRecord = SleepRecord(
        startEpochS = r.startTime.epochSecond,
        startOffsetS = (r.startZoneOffset ?: zone.rules.getOffset(r.startTime)).totalSeconds,
        endEpochS = r.endTime.epochSecond,
        endOffsetS = (r.endZoneOffset ?: zone.rules.getOffset(r.endTime)).totalSeconds,
        writer = r.metadata.dataOrigin.packageName,
        stages = r.stages.map { StageSpan(it.startTime.epochSecond, it.endTime.epochSecond, kindOf(it.stage)) },
    )

    private fun kindOf(stage: Int): StageKind = when (stage) {
        SleepSessionRecord.STAGE_TYPE_AWAKE,
        SleepSessionRecord.STAGE_TYPE_AWAKE_IN_BED,
        SleepSessionRecord.STAGE_TYPE_OUT_OF_BED,
        -> StageKind.AWAKE
        SleepSessionRecord.STAGE_TYPE_LIGHT -> StageKind.LIGHT
        SleepSessionRecord.STAGE_TYPE_DEEP -> StageKind.DEEP
        SleepSessionRecord.STAGE_TYPE_REM -> StageKind.REM
        else -> StageKind.OTHER
    }

    private companion object {
        const val MAX_PAGES = 10
    }
}

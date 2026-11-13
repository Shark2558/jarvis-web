// android/core/src/main/kotlin/io/github/shark2558/jarvis/core/Payloads.kt
// R7 D5, D6, D16, D17, D19: the bodies the phone sends, in phone-contract.md's key order and its
// one JSON form. Coordinates are integers of micro-degrees and travel only in the SOS body.
package io.github.shark2558.jarvis.core

data class StepsDay(val count: Long, val writer: String)

data class HeartDay(val min: Long, val avg: Long, val max: Long, val writer: String)

data class Stages(val awake: Long, val light: Long, val deep: Long, val rem: Long)

data class SleepSession(val start: String, val end: String, val writer: String, val stages: Stages?)

data class HealthDay(val date: String, val steps: StepsDay?, val heart: HeartDay?, val sleep: List<SleepSession>)

enum class SosKind(val word: String) {
    REAL("real"),
    TEST("test"),
    SAFE("safe"),
}

/** One location fix: micro-degrees, metres, its age in seconds and when it was taken. */
data class Fix(val latE6: Long, val lonE6: Long, val accuracyM: Long, val ageS: Long, val atEpochS: Long)

object Payloads {
    const val V = 1
    const val MAX_DAYS = 35

    data class Can(
        val notifications: Boolean,
        val healthRead: Boolean,
        val healthBackground: Boolean,
        val location: Boolean,
        val folder: Boolean,
        val tile: Boolean,
    )

    fun link(code: String, publicKeyHex: String, fingerprintHex: String, model: String, appVersion: String): ByteArray =
        CanonicalJson.bytes(
            Json.obj(
                "v" to V,
                "code" to code,
                "public_key" to publicKeyHex,
                "package" to Door.PACKAGE,
                "fingerprint" to fingerprintHex,
                "model" to model,
                "app_version" to appVersion,
            ),
        )

    fun hello(appVersion: String, versionCode: Int, model: String, android: Int, can: Can): ByteArray =
        CanonicalJson.bytes(
            Json.obj(
                "v" to V,
                "app_version" to appVersion,
                "version_code" to versionCode,
                "model" to model,
                "android" to android,
                "can" to Json.obj(
                    "notifications" to can.notifications,
                    "health_read" to can.healthRead,
                    "health_background" to can.healthBackground,
                    "location" to can.location,
                    "folder" to can.folder,
                    "tile" to can.tile,
                ),
            ),
        )

    fun health(days: List<HealthDay>): ByteArray {
        require(days.size <= MAX_DAYS) { "at most $MAX_DAYS days" }
        return CanonicalJson.bytes(Json.obj("v" to V, "days" to days.map { day(it) }))
    }

    private fun day(d: HealthDay): Json.Fields = Json.obj(
        "date" to d.date,
        "steps" to d.steps?.let { Json.obj("count" to it.count, "writer" to it.writer) },
        "heart" to d.heart?.let { Json.obj("min" to it.min, "avg" to it.avg, "max" to it.max, "writer" to it.writer) },
        "sleep" to d.sleep.map { s ->
            Json.obj(
                "start" to s.start,
                "end" to s.end,
                "writer" to s.writer,
                "stages" to s.stages?.let {
                    Json.obj("awake" to it.awake, "light" to it.light, "deep" to it.deep, "rem" to it.rem)
                },
            )
        },
    )

    /** The first line is the file's canonical JSON, then one newline, then the file's bytes. */
    fun inbox(name: String, mime: String, file: ByteArray): ByteArray {
        val first = CanonicalJson.bytes(
            Json.obj(
                "v" to V,
                "name" to name,
                "mime" to mime,
                "sha256" to Door.sha256Hex(file),
                "bytes" to file.size,
            ),
        )
        return first + byteArrayOf(NEWLINE) + file
    }

    fun sos(kind: SosKind, at: Long, fix: Fix?): ByteArray = CanonicalJson.bytes(
        Json.obj(
            "v" to V,
            "kind" to kind.word,
            "at" to at,
            "location" to fix?.let {
                Json.obj("lat_e6" to it.latE6, "lon_e6" to it.lonE6, "accuracy_m" to it.accuracyM, "age_s" to it.ageS)
            },
        ),
    )

    private const val NEWLINE: Byte = 0x0A
}

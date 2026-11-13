// android/core/src/test/kotlin/io/github/shark2558/jarvis/core/VectorsTest.kt
// R7 D6, D24: `core` against the SAME vectors the server is tested with
// (tests/fixtures/r7/phone_vectors.json): every body's SHA-256, the exact signing string, the
// header, the payloads' JSON bytes (rebuilt from each case's payload) and the public key. The
// signatures are checked with the JDK's own SHA256withECDSA, the algorithm Android Keystore signs
// with, so the app's signature form is the one the server verifies.
package io.github.shark2558.jarvis.core

import java.io.File
import java.security.KeyFactory
import java.security.PublicKey
import java.security.Signature
import java.security.spec.X509EncodedKeySpec

private const val DEFAULT_VECTORS = "../../tests/fixtures/r7/phone_vectors.json"

fun vectors(): Map<String, Any?> {
    val path = System.getProperty("jarvis.vectors") ?: DEFAULT_VECTORS
    val file = File(path)
    check(file.isFile) { "the shared vectors are missing: $path" }
    return MiniJson.parse(file.readText(Charsets.UTF_8)).asMap()
}

private fun vectorList(): List<Map<String, Any?>> = vectors()["cases"].asList().map { it.asMap() }

private fun headerParts(header: String): Map<String, String> =
    header.split(";").associate { part ->
        val eq = part.indexOf('=')
        if (eq < 0) part to "" else part.substring(0, eq) to part.substring(eq + 1)
    }

private fun publicKey(v: Map<String, Any?>): PublicKey =
    KeyFactory.getInstance("EC").generatePublic(
        X509EncodedKeySpec(Door.unhex(v.text("public_key_spki_der_hex"))),
    )

private fun signingOf(v: Map<String, Any?>, case: Map<String, Any?>): ByteArray =
    Door.signingString(
        v.text("device_id"),
        case.whole("t"),
        case.text("nonce"),
        case.text("method"),
        case.text("path"),
        case.text("body").toByteArray(Charsets.UTF_8),
    )

private fun helloBody(p: Map<String, Any?>): ByteArray {
    val can = p["can"].asMap()
    return Payloads.hello(
        appVersion = p.text("app_version"),
        versionCode = p.whole("version_code").toInt(),
        model = p.text("model"),
        android = p.whole("android").toInt(),
        can = Payloads.Can(
            notifications = can.flag("notifications"),
            healthRead = can.flag("health_read"),
            healthBackground = can.flag("health_background"),
            location = can.flag("location"),
            folder = can.flag("folder"),
            tile = can.flag("tile"),
        ),
    )
}

private fun dayOf(d: Map<String, Any?>): HealthDay {
    val steps = d["steps"]?.asMap()
    val heart = d["heart"]?.asMap()
    val sleep = d["sleep"].asList().map { it.asMap() }.map { s ->
        val st = s["stages"]?.asMap()
        SleepSession(
            start = s.text("start"),
            end = s.text("end"),
            writer = s.text("writer"),
            stages = st?.let { Stages(it.whole("awake"), it.whole("light"), it.whole("deep"), it.whole("rem")) },
        )
    }
    return HealthDay(
        date = d.text("date"),
        steps = steps?.let { StepsDay(it.whole("count"), it.text("writer")) },
        heart = heart?.let { HeartDay(it.whole("min"), it.whole("avg"), it.whole("max"), it.text("writer")) },
        sleep = sleep,
    )
}

private fun sosBody(p: Map<String, Any?>): ByteArray {
    val kind = SosKind.entries.first { it.word == p.text("kind") }
    val loc = p["location"]?.asMap()
    val fix = loc?.let {
        Fix(
            latE6 = it.whole("lat_e6"),
            lonE6 = it.whole("lon_e6"),
            accuracyM = it.whole("accuracy_m"),
            ageS = it.whole("age_s"),
            atEpochS = p.whole("at"),
        )
    }
    return Payloads.sos(kind, p.whole("at"), fix)
}

fun vectorCases(): List<Case> = cases(
    "vectors",
    "every case has a body digest, a signing string and a header" to {
        val all = vectorList()
        yes(all.size >= 9, "the vectors hold nine cases or more (found ${all.size})")
        for (case in all) {
            val body = case.text("body").toByteArray(Charsets.UTF_8)
            same(case.text("body_sha256_hex"), Door.sha256Hex(body), "${case.text("name")} body sha256")
        }
    },
    "the signing string equals the vectors byte for byte" to {
        val v = vectors()
        for (case in vectorList()) {
            sameBytes(case.text("string").toByteArray(Charsets.US_ASCII), signingOf(v, case), "${case.text("name")} string")
        }
    },
    "the header is written exactly as the vectors" to {
        val v = vectors()
        for (case in vectorList()) {
            val parts = headerParts(case.text("header"))
            val signature = Door.unb64url(parts.getValue("s"))
            val written = Door.header(v.text("device_id"), case.whole("t"), case.text("nonce"), signature)
            same(case.text("header"), written, "${case.text("name")} header")
        }
    },
    "the server's verifier and the JDK's SHA256withECDSA agree on every case" to {
        val v = vectors()
        val key = publicKey(v)
        for (case in vectorList()) {
            val verifier = Signature.getInstance("SHA256withECDSA")
            verifier.initVerify(key)
            verifier.update(signingOf(v, case))
            val sig = Door.unb64url(headerParts(case.text("header")).getValue("s"))
            same(case.flag("verifies"), verifier.verify(sig), "${case.text("name")} verifies")
        }
    },
    "the hello, health and sos payloads rebuild the exact body bytes" to {
        var rebuilt = 0
        for (case in vectorList()) {
            val payload = case["payload"]?.asMap() ?: continue
            val expected = case.text("body").toByteArray(Charsets.UTF_8)
            val actual = when (case.text("path")) {
                "/phone/v1/hello" -> helloBody(payload)
                "/phone/v1/health" -> Payloads.health(payload["days"].asList().map { dayOf(it.asMap()) })
                "/phone/v1/sos" -> sosBody(payload)
                else -> throw CheckFailed("a payload for an unexpected path ${case.text("path")}")
            }
            sameBytes(expected, actual, "${case.text("name")} body")
            rebuilt += 1
        }
        yes(rebuilt >= 4, "hello, health, sos and sos_no_location were rebuilt (found $rebuilt)")
    },
    "the inbox body is its first line, one newline, then the file's bytes" to {
        val case = vectorList().first { it.text("name") == "inbox" }
        val body = case.text("body").toByteArray(Charsets.UTF_8)
        val cut = body.indexOf('\n'.code.toByte())
        val file = body.copyOfRange(cut + 1, body.size)
        val first = case["first_line"].asMap()
        same(first.text("sha256"), Door.sha256Hex(file), "the file's sha256")
        same(first.whole("bytes"), file.size.toLong(), "the file's size")
        sameBytes(body, Payloads.inbox(first.text("name"), first.text("mime"), file), "inbox body")
    },
    "the public key in X9.62 form is the tail of its SubjectPublicKeyInfo" to {
        val v = vectors()
        val point = Door.x962FromSpki(Door.unhex(v.text("public_key_spki_der_hex")))
        same(v.text("public_key_x962_hex"), Door.hex(point), "x962 public key")
        same(65, point.size, "an uncompressed P-256 point is 65 bytes")
    },
    "the package, scheme and header name are the contract's" to {
        val v = vectors()
        same(v.text("package"), Door.PACKAGE, "package")
        same(v.text("scheme"), Door.SCHEME, "scheme")
        same(v.text("header"), Door.HEADER, "header name")
    },
    "every refused path is refused before signing" to {
        val v = vectors()
        val paths = v["refused_paths"].asList().map { it as String }
        yes(paths.isNotEmpty(), "the vectors list refused paths")
        for (p in paths) {
            yes(!Door.isDoorPath(p), "$p is not a door path")
            refuses<IllegalArgumentException>("signing $p") {
                Door.signingString(v.text("device_id"), 1L, "0".repeat(32), "POST", p, ByteArray(0))
            }
        }
    },
)

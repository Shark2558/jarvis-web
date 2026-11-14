// android/core/src/test/kotlin/io/github/shark2558/jarvis/core/JsonDoorTest.kt
// R7 D6, D24: the one JSON form (phone-contract.md section 4) and the door's small rules. The
// expected strings were written by the server's own `canonical_json` (Python's json.dumps with
// ensure_ascii=False and no spaces).
package io.github.shark2558.jarvis.core

fun jsonCases(): List<Case> = cases(
    "json",
    "strings escape quote, backslash and control characters as Python's json does" to {
        val text = "a\"b\\c\n\r\t\b\u000C\u0001\u001F\u007F \u00E9/\u00FC\u2028\uD83D\uDE00"
        val expected = "\"a\\\"b\\\\c\\n\\r\\t\\b\\f\\u0001\\u001f\u007F \u00E9/\u00FC\u2028\uD83D\uDE00\""
        same(expected, CanonicalJson.write(Json.of(text)), "escaped string")
    },
    "lists, objects, booleans, null and negative numbers have no spaces" to {
        val value = Json.obj(
            "k" to listOf(1, -2L, true, false, null, "x"),
            "e" to Json.obj(),
            "l" to emptyList<Any?>(),
        )
        same("{\"k\":[1,-2,true,false,null,\"x\"],\"e\":{},\"l\":[]}", CanonicalJson.write(value), "shape")
    },
    "keys keep the order they were given in" to {
        same("{\"z\":1,\"a\":2}", CanonicalJson.write(Json.obj("z" to 1, "a" to 2)), "order")
    },
    "a fraction is refused: payloads carry integers only" to {
        refuses<IllegalArgumentException>("a Double") { Json.obj("lat" to 12.97) }
        refuses<IllegalArgumentException>("a Float") { Json.of(1.5f) }
    },
    "a key given twice is refused" to {
        refuses<IllegalArgumentException>("a repeated key") { Json.obj("a" to 1, "a" to 2) }
    },
    "a lone surrogate is refused (it has no UTF-8 form)" to {
        refuses<IllegalArgumentException>("a lone high surrogate") { CanonicalJson.write(Json.of("x\uD83D")) }
        refuses<IllegalArgumentException>("a lone low surrogate") { CanonicalJson.write(Json.of("\uDE00x")) }
    },
    "the bytes are UTF-8 with no byte-order mark" to {
        val bytes = CanonicalJson.bytes(Json.of("\u00E9"))
        sameBytes(byteArrayOf(0x22, 0xC3.toByte(), 0xA9.toByte(), 0x22), bytes, "UTF-8")
    },
    "the link request is written in the contract's key order" to {
        val body = Payloads.link(
            code = "ABCD2345",
            publicKeyHex = "04" + "ab".repeat(64),
            fingerprintHex = "8c90472edc53d89695593b5cbb88e2a62d9a8802c6cbee6aaeaf6987cd685142",
            model = "phone",
            appVersion = "7.0.0",
        )
        val expected = "{\"v\":1,\"code\":\"ABCD2345\",\"public_key\":\"04" + "ab".repeat(64) +
            "\",\"package\":\"io.github.shark2558.jarvis\",\"fingerprint\":" +
            "\"8c90472edc53d89695593b5cbb88e2a62d9a8802c6cbee6aaeaf6987cd685142\"," +
            "\"model\":\"phone\",\"app_version\":\"7.0.0\"}"
        same(expected, String(body, Charsets.UTF_8), "link body")
    },
    "an inbox name is escaped inside its first line" to {
        val body = Payloads.inbox("a \"b\"\n.pdf", "application/pdf", byteArrayOf(1, 2, 3))
        val first = String(body, Charsets.UTF_8).substringBefore('\n')
        val expected = "{\"v\":1,\"name\":\"a \\\"b\\\"\\n.pdf\",\"mime\":\"application/pdf\",\"sha256\":\"" +
            Door.sha256Hex(byteArrayOf(1, 2, 3)) + "\",\"bytes\":3}"
        same(expected, first, "inbox first line")
        same(expected.length + 1 + 3, body.size, "first line, one newline, three bytes")
    },
)

fun doorCases(): List<Case> = cases(
    "door",
    "only the four routes are door paths" to {
        for (route in listOf("hello", "health", "inbox", "sos")) {
            same("/phone/v1/$route", Door.path(route), "path of $route")
            yes(Door.isDoorPath(Door.path(route)), "$route is a door path")
        }
        refuses<IllegalArgumentException>("an unknown route") { Door.path("vault") }
        yes(!Door.isDoorPath("/phone/v1/hello/"), "a trailing slash is not a door path")
        yes(!Door.isDoorPath("/PHONE/v1/hello"), "the path is case-sensitive")
    },
    "the signing string refuses another method" to {
        refuses<IllegalArgumentException>("PUT") {
            Door.signingString("ph_3f9a2c7e1b04", 1L, "0".repeat(32), "PUT", "/phone/v1/hello", ByteArray(0))
        }
    },
    "the signing string refuses a character outside ASCII" to {
        refuses<IllegalArgumentException>("a device id with an accent") {
            Door.signingString("ph_\u00E9", 1L, "0".repeat(32), "POST", "/phone/v1/hello", ByteArray(0))
        }
    },
    "the header refuses a malformed device id, nonce, time or signature" to {
        val sig = byteArrayOf(1, 2, 3)
        refuses<IllegalArgumentException>("device id") { Door.header("ph_XYZ", 1L, "0".repeat(32), sig) }
        refuses<IllegalArgumentException>("nonce") { Door.header("ph_3f9a2c7e1b04", 1L, "0".repeat(31), sig) }
        refuses<IllegalArgumentException>("time") { Door.header("ph_3f9a2c7e1b04", -1L, "0".repeat(32), sig) }
        refuses<IllegalArgumentException>("signature") { Door.header("ph_3f9a2c7e1b04", 1L, "0".repeat(32), ByteArray(0)) }
    },
    "a nonce is 16 random bytes in lowercase hex" to {
        val a = Door.newNonce()
        val b = Door.newNonce()
        yes(Regex("[0-9a-f]{32}").matches(a), "nonce shape: $a")
        yes(a != b, "two nonces differ")
    },
    "hex and base64url round-trip" to {
        val data = byteArrayOf(0, 1, 127, -128, -1)
        sameBytes(data, Door.unhex(Door.hex(data)), "hex")
        same("AAF_gP8", Door.b64url(data), "base64url without padding")
        sameBytes(data, Door.unb64url("AAF_gP8"), "base64url back")
        refuses<IllegalArgumentException>("odd hex") { Door.unhex("abc") }
        refuses<IllegalArgumentException>("upper-case hex") { Door.unhex("AB") }
    },
    "a key that is not P-256 is refused" to {
        refuses<IllegalArgumentException>("a short key") { Door.x962FromSpki(ByteArray(10)) }
        val v = vectors()
        val spki = Door.unhex(v.text("public_key_spki_der_hex"))
        spki[3] = 0x14
        refuses<IllegalArgumentException>("another algorithm") { Door.x962FromSpki(spki) }
    },
    "a device id is ph_ and 12 lowercase hex characters" to {
        yes(Door.isDeviceId("ph_3f9a2c7e1b04"), "a good device id")
        yes(!Door.isDeviceId("ph_3F9A2C7E1B04"), "upper case is not a device id")
        yes(!Door.isDeviceId("ph_3f9a2c7e1b0"), "eleven characters is not a device id")
    },
)

// android/core/src/test/kotlin/io/github/shark2558/jarvis/core/CallsTest.kt
// R18 D: the phone's half of JARVIS calls against the SAME vectors the server is tested with
// (tests/fixtures/r18/phone_calls_vectors.json): every good command verifies and reads, every bad
// signature fails, the refused ones are refused for their reason, and the calls door body is the
// server's bytes exactly. Fresh keys made here cover the checks the vectors cannot (a command made
// in the future, one that lives too long, one already acted on). Then the strict JSON reader, the
// numbers and the rings.
package io.github.shark2558.jarvis.core

import java.io.File
import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.Signature
import java.security.spec.ECGenParameterSpec

private const val DEFAULT_CALL_VECTORS = "../../tests/fixtures/r18/phone_calls_vectors.json"

fun callVectors(): Map<String, Any?> {
    val path = System.getProperty("jarvis.calls_vectors") ?: DEFAULT_CALL_VECTORS
    val file = File(path)
    check(file.isFile) { "the shared call vectors are missing: $path" }
    return MiniJson.parse(file.readText(Charsets.UTF_8)).asMap()
}

private fun cases(v: Map<String, Any?>, key: String): List<Map<String, Any?>> = v[key].asList().map { it.asMap() }

private fun freshKey(): KeyPair = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()

private fun keyHex(pair: KeyPair): String = Door.hex(Door.x962FromSpki(pair.public.encoded))

private fun signed(pair: KeyPair, body: String): String {
    val s = Signature.getInstance("SHA256withECDSA")
    s.initSign(pair.private)
    s.update(CallCommands.signingBytes(body))
    return Door.b64url(s.sign())
}

private fun endBody(id: String, iat: Long, exp: Long, device: String = "ph_0123456789ab"): String =
    CanonicalJson.write(
        Json.obj("v" to 1, "id" to id, "d" to device, "type" to "call.end", "iat" to iat, "exp" to exp, "call_id" to "call_000000000001"),
    )

fun callCases(): List<Case> = cases(
    "calls",
    "every good vector verifies with the cloud's key and reads as its type" to {
        val v = callVectors()
        val key = v.text("public_key")
        same(CallWire.SCHEME, v.text("scheme"), "the scheme")
        val types = ArrayList<String>()
        for (case in cases(v, "good")) {
            val body = case.text("body")
            yes(CallCommands.verify(key, body, case.text("sig")), "verifies: ${case.text("name")}")
            val cmd = CallCommands.read(body)
            yes(cmd != null, "reads: ${case.text("name")}")
            same(v.text("device_id"), cmd!!.head.device, "the device")
            types.add(cmd.head.type)
        }
        same(listOf("call.dial", "call.answer", "call.end", "call.route", "call.card"), types, "one of each")
    },
    "the dial and the card carry their fields as written, escapes included" to {
        val v = callVectors()
        val good = cases(v, "good").associateBy { it.text("name") }
        val dial = CallCommands.read(good.getValue("dial").text("body")) as DialCommand
        same("+919000000001", dial.number, "number")
        same("ap_live_000001", dial.approvalId, "approval")
        same("Laundry \u0d32\u0d3e", dial.label, "a Malayalam label")
        same("call_000000000001", dial.subject, "subject")
        val card = CallCommands.read(good.getValue("card").text("body")) as CardCommand
        same("Dr \"Rao\"", card.label, "quotes kept")
        same("Book Saturday 10:00-12:00 no payment", card.purpose, "the purpose on one line")
        yes(card.passkey, "a new number needs the passkey")
        val route = CallCommands.read(good.getValue("route").text("body")) as RouteCommand
        same("phone", route.to, "route")
    },
    "every bad signature fails" to {
        val v = callVectors()
        for (case in cases(v, "bad_signature")) {
            yes(!CallCommands.verify(v.text("public_key"), case.text("body"), case.text("sig")), "fails: ${case.text("name")}")
            same(CommandVerdict.BAD_SIGNATURE, CallCommands.check(v.text("public_key"), case.text("body"), case.text("sig"), v.text("device_id"), v.whole("now")) { false }.verdict, case.text("name"))
        }
    },
    "a command for another phone, or past its time, is refused for that reason" to {
        val v = callVectors()
        val want = mapOf("device" to CommandVerdict.OTHER_PHONE, "expired" to CommandVerdict.EXPIRED)
        for (case in cases(v, "refused")) {
            val now = (case["now"] as? Number)?.toLong() ?: v.whole("now")
            val got = CallCommands.check(v.text("public_key"), case.text("body"), case.text("sig"), v.text("device_id"), now) { false }
            same(want.getValue(case.text("why")), got.verdict, case.text("name"))
            yes(got.command == null, "nothing to act on")
        }
    },
    "a good command is acted on once, and the checks run in their order" to {
        val pair = freshKey()
        val key = keyHex(pair)
        val now = 1_800_000_000L
        val body = endBody("pc_00000000000000e1", now, now + 120)
        val sig = signed(pair, body)
        val ok = CallCommands.check(key, body, sig, "ph_0123456789ab", now) { false }
        same(CommandVerdict.ACT, ok.verdict, "acts")
        same("call.end", ok.command!!.head.type, "the command")
        same(CommandVerdict.SEEN, CallCommands.check(key, body, sig, "ph_0123456789ab", now) { it == "pc_00000000000000e1" }.verdict, "once")
        val future = endBody("pc_00000000000000e2", now + 600, now + 700)
        same(CommandVerdict.NOT_YET, CallCommands.check(key, future, signed(pair, future), "ph_0123456789ab", now) { false }.verdict, "made in the future")
        val long = endBody("pc_00000000000000e3", now, now + 3_600)
        same(CommandVerdict.TOO_LONG, CallCommands.check(key, long, signed(pair, long), "ph_0123456789ab", now) { false }.verdict, "lives too long")
        same(CommandVerdict.BAD_SIGNATURE, CallCommands.check(keyHex(freshKey()), body, sig, "ph_0123456789ab", now) { false }.verdict, "another key")
    },
    "a signed body of another form or with other keys is not read" to {
        val pair = freshKey()
        val key = keyHex(pair)
        val now = 1_800_000_000L
        val good = endBody("pc_00000000000000f1", now, now + 120)
        val bad = listOf(
            good.replace(",", ", "),
            good.replace("\"call.end\"", "\"call.record\""),
            good.replace("}", ",\"extra\":1}"),
            good.replace("\"call_000000000001\"", "\"call_1\""),
            CanonicalJson.write(Json.obj("v" to 2, "id" to "pc_00000000000000f1", "d" to "ph_0123456789ab", "type" to "call.end", "iat" to now, "exp" to now + 1, "call_id" to "call_000000000001")),
            CanonicalJson.write(
                Json.obj(
                    "v" to 1, "id" to "pc_00000000000000f1", "d" to "ph_0123456789ab", "type" to "call.dial", "iat" to now, "exp" to now + 60,
                    "call_id" to "call_000000000001", "number" to "112", "approval_id" to "ap_live_000001", "label" to "",
                ),
            ),
        )
        for (body in bad) {
            same(CommandVerdict.BAD_FORM, CallCommands.check(key, body, signed(pair, body), "ph_0123456789ab", now) { false }.verdict, body)
        }
        yes(!CallCommands.verify("04" + "00".repeat(64), good, signed(pair, good)), "a key off the curve")
        yes(!CallCommands.verify(key, good, signed(pair, good) + "="), "padding is not the form")
    },
    "a dial is placed without a tap only while it is fresh" to {
        val head = CommandHead("pc_00000000000000d1", "ph_0123456789ab", "call.dial", 1_000L, 1_300L)
        val dial = DialCommand(head, "call_000000000001", "+919000000001", "ap_live_000001", "")
        yes(CallCommands.autoDial(dial, 1_000L + CallCommands.AUTO_DIAL_S), "fresh")
        yes(!CallCommands.autoDial(dial, 1_001L + CallCommands.AUTO_DIAL_S), "stale: he taps")
        yes(!CallCommands.autoDial(dial, 1_300L), "expired")
    },
    "the calls door body is the server's bytes exactly" to {
        val v = callVectors()
        val events = listOf(
            StateEvent("pe_00000000000000a1", null, "ringing", "+919000000001", 5, 1_800_000_000L),
            ResultEvent("pe_00000000000000a2", "pc_0000000000000001", "call_000000000001", "call.dial", false, "needs_tap", 1_800_000_000L),
            DecisionEvent("pe_00000000000000a3", "cc_000000000001", "approve", 1_800_000_000L),
        )
        val body = CallPayloads.body("18.0.0", CallCan(true, true, true, false, true), events, listOf("pc_0000000000000002"), 8)
        sameBytes(v.text("door_body").toByteArray(Charsets.UTF_8), body, "the door body")
        for (e in events) same(e, CallPayloads.decode(CallPayloads.encode(e)), "an event survives the queue")
    },
    "events of the wrong shape cannot be made, and the body has its limits" to {
        refuses<IllegalArgumentException>("a number while active") { StateEvent("pe_00000000000000a1", null, "active", "+919000000001", 0, 1L) }
        refuses<IllegalArgumentException>("an unknown state") { StateEvent("pe_00000000000000a1", null, "held", null, 0, 1L) }
        refuses<IllegalArgumentException>("a bad event id") { StateEvent("pe_1", null, "ended", null, 0, 1L) }
        refuses<IllegalArgumentException>("a bad code") { ResultEvent("pe_00000000000000a1", "pc_0000000000000001", null, "call.end", true, "Ended!", 1L) }
        refuses<IllegalArgumentException>("a bad decision") { DecisionEvent("pe_00000000000000a1", "cc_000000000001", "maybe", 1L) }
        val e = StateEvent("pe_00000000000000a1", null, "ended", null, 0, 1L)
        val can = CallCan(true, true, true, true, true)
        refuses<IllegalArgumentException>("nine events") { CallPayloads.body("18.0.0", can, List(9) { e }, emptyList(), 0) }
        refuses<IllegalArgumentException>("a long wait") { CallPayloads.body("18.0.0", can, emptyList(), emptyList(), 26) }
        yes(CallPayloads.decode("{\"id\":\"pe_00000000000000a1\",\"type\":\"call.state\"}") == null, "a broken line is dropped")
        yes(CallWire.EVENT_ID.matches(CallPayloads.newEventId()), "a fresh event id")
    },
    "the door's answer is read, and anything unreadable is nothing" to {
        val key = keyHex(freshKey())
        val text = "{\"v\":1,\"key\":\"$key\",\"answering\":{\"on\":true,\"after_rings\":5,\"number\":true},\"took\":1," +
            "\"commands\":[{\"body\":\"{}\",\"sig\":\"AA\"}],\"decisions\":[{\"card_id\":\"cc_000000000001\",\"outcome\":\"passkey_needed\"}]}"
        val a = CallPayloads.answer(text)!!
        same(key, a.key, "the key")
        yes(a.answeringOn && a.sendNumber && a.afterRings == 5, "answering")
        same(listOf("{}" to "AA"), a.commands, "commands")
        same(listOf("cc_000000000001" to "passkey_needed"), a.decisions, "decisions")
        yes(CallPayloads.answer("{\"v\":1,\"key\":\"04\"}") == null, "no key")
        yes(CallPayloads.answer("<html>") == null, "not JSON")
    },
    "the JSON reader takes the door's JSON and refuses anything looser" to {
        val v = JsonRead.parse(" {\"a\":[1,-2,true,null,\"x\\u00e9\\n\\\"\"],\"b\":{}} ") as Json.Fields
        same(listOf("a", "b"), v.keys(), "keys in order")
        same(Json.Items(listOf(Json.Num(1), Json.Num(-2), Json.Bool(true), Json.Null, Json.Text("x\u00e9\n\""))), v.field("a"), "values")
        for (bad in listOf("1.5", "1e3", "01", "{\"a\":1,\"a\":2}", "{} x", "\"a\u0001\"", "[1,]", "{\"a\"}", "", "nul", "\"\\q\"", "[".repeat(40))) {
            yes(JsonRead.parseOrNull(bad) == null, "refused: $bad")
        }
    },
    "a caller's number becomes E.164, and only its last two digits are ever shown" to {
        same("+919000000001", CallRules.e164("09000000001"), "trunk zero")
        same("+919000000001", CallRules.e164("+91 90000 00001"), "spaces")
        same("+919000000001", CallRules.e164("9000000001"), "ten digits")
        same("+919000000001", CallRules.e164("919000000001"), "country code without +")
        same("+14155550100", CallRules.e164("0014155550100"), "international 00")
        for (none in listOf(null, "", "Private", "12345", "+0123")) same(null, CallRules.e164(none), "none: $none")
        same("+91********01", CallRules.mask("+919000000001"), "masked")
        same("**", CallRules.mask("12"), "short")
        yes(CallWire.DIAL_NUMBER.matches("+919000000001") && !CallWire.DIAL_NUMBER.matches("+91112"), "the dial shape")
    },
    "rings are counted from the first, every three seconds" to {
        same(1, CallRules.rings(1_000L, 1_000L), "the first")
        same(1, CallRules.rings(1_000L, 3_999L), "still the first")
        same(5, CallRules.rings(0L, 12_000L), "the fifth at 12 s")
        same(12_000L, CallRules.msUntilRing(5), "ring five")
        same(60, CallRules.rings(0L, 10_000_000L), "capped")
    },
)

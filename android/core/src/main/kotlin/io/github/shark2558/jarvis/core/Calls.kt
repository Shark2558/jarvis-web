// android/core/src/main/kotlin/io/github/shark2558/jarvis/core/Calls.kt
// R18 D: the phone's half of JARVIS calls on the wire, as src/jarvis/phone/calls_wire.py writes it
// (shared vectors: tests/fixtures/r18/phone_calls_vectors.json).
//
// A command from the cloud is the one JSON form of {v, id, d, type, iat, exp, ...its fields}
// signed ECDSA P-256 / SHA-256 (DER, base64url) over "jarvis-cloud-v1\n" + the body's UTF-8 bytes.
// The phone acts on one only when, in this order: the signature verifies with the key the door's
// answer gave; the body is exactly its one form with exactly its type's keys; `d` is this phone;
// it has not expired, was not made in the future and lives at most 15 minutes; its id was never
// acted on. A dial also carries an Indian number of the one shape (+91 and ten digits).
//
// What the phone sends: the `calls` door body {v, app_version, can, events, acks, wait}, with
// call.state, call.result and card.decision events in the server's key order.
package io.github.shark2558.jarvis.core

import java.security.GeneralSecurityException
import java.security.KeyFactory
import java.security.SecureRandom
import java.security.Signature
import java.security.spec.X509EncodedKeySpec

object CallWire {
    const val SCHEME = "jarvis-cloud-v1"
    const val ROUTE = "calls"
    const val MAX_EVENTS = 8
    const val MAX_ACKS = 16
    const val MAX_WAIT_S = 25
    const val MAX_LABEL = 40
    const val MAX_PURPOSE = 120
    val CALL_ID = Regex("call_[0-9a-f]{12}")
    val CARD_ID = Regex("cc_[0-9a-f]{12}")
    val COMMAND_ID = Regex("pc_[0-9a-f]{16}")
    val EVENT_ID = Regex("pe_[0-9a-f]{16}")
    val APPROVAL_ID = Regex("[A-Za-z0-9_-]{8,128}")
    val DIAL_NUMBER = Regex("\\+91[1-9][0-9]{9}")
    val E164 = Regex("\\+[1-9][0-9]{6,14}")
    val CODE = Regex("[a-z_]{1,32}")
    val STATES = setOf("ringing", "dialing", "active", "ended")
    val COMMANDS = setOf("call.dial", "call.answer", "call.end", "call.route", "call.card")
    val ROUTES = setOf("phone", "bluetooth")
    private val KEY = Regex("04[0-9a-f]{128}")

    fun isKey(hex: String): Boolean = KEY.matches(hex)
}

data class CommandHead(val id: String, val device: String, val type: String, val iat: Long, val exp: Long)

sealed interface CallCommand {
    val head: CommandHead

    /** The call (or card) the command is about. */
    val subject: String
}

data class DialCommand(
    override val head: CommandHead,
    val callId: String,
    val number: String,
    val approvalId: String,
    val label: String,
) : CallCommand {
    override val subject: String get() = callId
}

data class AnswerCommand(override val head: CommandHead, val callId: String) : CallCommand {
    override val subject: String get() = callId
}

data class EndCommand(override val head: CommandHead, val callId: String) : CallCommand {
    override val subject: String get() = callId
}

data class RouteCommand(override val head: CommandHead, val callId: String, val to: String) : CallCommand {
    override val subject: String get() = callId
}

data class CardCommand(
    override val head: CommandHead,
    val cardId: String,
    val label: String,
    val purpose: String,
    val passkey: Boolean,
) : CallCommand {
    override val subject: String get() = cardId
}

enum class CommandVerdict(val code: String) {
    ACT("act"),
    BAD_SIGNATURE("bad_signature"),
    BAD_FORM("bad_form"),
    OTHER_PHONE("other_phone"),
    EXPIRED("expired"),
    NOT_YET("not_yet"),
    TOO_LONG("too_long"),
    SEEN("seen"),
}

data class Checked(val verdict: CommandVerdict, val command: CallCommand?)

object CallCommands {
    const val SKEW_S = 120L
    const val MAX_LIFE_S = 900L

    /** A dial is placed without his tap only this soon after the cloud made it (else he taps). */
    const val AUTO_DIAL_S = 120L
    private val COMMON = listOf("v", "id", "d", "type", "iat", "exp")
    private val KEYS: Map<String, List<String>> = mapOf(
        "call.dial" to COMMON + listOf("call_id", "number", "approval_id", "label"),
        "call.answer" to COMMON + listOf("call_id"),
        "call.end" to COMMON + listOf("call_id"),
        "call.route" to COMMON + listOf("call_id", "to"),
        "call.card" to COMMON + listOf("card_id", "label", "purpose", "passkey"),
    )

    fun signingBytes(body: String): ByteArray = "${CallWire.SCHEME}\n".toByteArray(Charsets.US_ASCII) + body.toByteArray(Charsets.UTF_8)

    /** The cloud's signature over the body, with its key (65-byte X9.62 point as lowercase hex). */
    fun verify(keyHex: String, body: String, sig: String): Boolean {
        if (!CallWire.isKey(keyHex) || sig.isEmpty() || sig.contains('=')) return false
        return try {
            val spec = X509EncodedKeySpec(Door.spkiFromX962(Door.unhex(keyHex)))
            val key = KeyFactory.getInstance("EC").generatePublic(spec)
            val verifier = Signature.getInstance("SHA256withECDSA")
            verifier.initVerify(key)
            verifier.update(signingBytes(body))
            verifier.verify(Door.unb64url(sig))
        } catch (e: GeneralSecurityException) {
            false
        } catch (e: IllegalArgumentException) {
            false
        }
    }

    /** The command, only when `body` is exactly its one form with exactly its type's keys. */
    fun read(body: String): CallCommand? {
        val value = JsonRead.parseOrNull(body) as? Json.Fields ?: return null
        if (CanonicalJson.write(value) != body) return null
        val type = value.textOf("type") ?: return null
        if (value.keys() != KEYS[type]) return null
        val head = head(value, type) ?: return null
        return try {
            command(value, head)
        } catch (e: IllegalArgumentException) {
            null
        }
    }

    private fun head(value: Json.Fields, type: String): CommandHead? {
        if (value.longOf("v") != 1L) return null
        val id = value.textOf("id")?.takeIf { CallWire.COMMAND_ID.matches(it) } ?: return null
        val device = value.textOf("d")?.takeIf { Door.isDeviceId(it) } ?: return null
        val iat = value.longOf("iat")?.takeIf { it >= 0 } ?: return null
        val exp = value.longOf("exp")?.takeIf { it >= 0 } ?: return null
        return CommandHead(id, device, type, iat, exp)
    }

    private fun command(v: Json.Fields, head: CommandHead): CallCommand = when (head.type) {
        "call.dial" -> DialCommand(
            head,
            shaped(v, "call_id", CallWire.CALL_ID),
            shaped(v, "number", CallWire.DIAL_NUMBER),
            shaped(v, "approval_id", CallWire.APPROVAL_ID),
            text(v, "label", 0, CallWire.MAX_LABEL),
        )
        "call.answer" -> AnswerCommand(head, shaped(v, "call_id", CallWire.CALL_ID))
        "call.end" -> EndCommand(head, shaped(v, "call_id", CallWire.CALL_ID))
        "call.route" -> {
            val to = text(v, "to", 1, CallWire.MAX_LABEL)
            require(to in CallWire.ROUTES) { "not a route" }
            RouteCommand(head, shaped(v, "call_id", CallWire.CALL_ID), to)
        }
        "call.card" -> CardCommand(
            head,
            shaped(v, "card_id", CallWire.CARD_ID),
            text(v, "label", 1, CallWire.MAX_LABEL),
            text(v, "purpose", 0, CallWire.MAX_PURPOSE),
            requireNotNull(v.boolOf("passkey")) { "no passkey flag" },
        )
        else -> throw IllegalArgumentException("not a command type")
    }

    private fun shaped(v: Json.Fields, key: String, shape: Regex): String {
        val t = v.textOf(key)
        require(t != null && shape.matches(t)) { "not the shape of $key" }
        return t
    }

    private fun text(v: Json.Fields, key: String, min: Int, max: Int): String {
        val t = v.textOf(key)
        require(t != null && t.length in min..max) { "not the length of $key" }
        return t
    }

    /** Every check, in the order the module comment gives. `seen` says an id was acted on. */
    fun check(keyHex: String, body: String, sig: String, deviceId: String, nowS: Long, seen: (String) -> Boolean): Checked {
        if (!verify(keyHex, body, sig)) return Checked(CommandVerdict.BAD_SIGNATURE, null)
        val cmd = read(body) ?: return Checked(CommandVerdict.BAD_FORM, null)
        val h = cmd.head
        val verdict = when {
            h.device != deviceId -> CommandVerdict.OTHER_PHONE
            h.exp <= nowS -> CommandVerdict.EXPIRED
            h.iat > nowS + SKEW_S -> CommandVerdict.NOT_YET
            h.exp - h.iat > MAX_LIFE_S -> CommandVerdict.TOO_LONG
            seen(h.id) -> CommandVerdict.SEEN
            else -> CommandVerdict.ACT
        }
        return Checked(verdict, if (verdict == CommandVerdict.ACT) cmd else null)
    }

    /** Fresh enough to dial with no tap; otherwise the notification asks him to tap. */
    fun autoDial(cmd: DialCommand, nowS: Long): Boolean = nowS - cmd.head.iat <= AUTO_DIAL_S && nowS < cmd.head.exp
}

object CallRules {
    /** India's ring cadence repeats about every 3 seconds (0.4 on, 0.2 off, 0.4 on, 2 off). */
    const val RING_PERIOD_MS = 3_000L
    const val MAX_RINGS = 60
    private const val LOCAL_DIGITS = 10
    private const val TRUNK_DIGITS = 11
    private const val COUNTRY_DIGITS = 12

    fun rings(startMs: Long, nowMs: Long): Int =
        (1L + (nowMs - startMs).coerceAtLeast(0L) / RING_PERIOD_MS).coerceIn(1L, MAX_RINGS.toLong()).toInt()

    /** How long after the first ring the n-th ring comes. */
    fun msUntilRing(n: Int): Long = (n - 1).coerceAtLeast(0) * RING_PERIOD_MS

    /** A caller's number as Android gives it ("09000000001", "+91 90000 00001", ...) in E.164,
     *  or null (a withheld or unreadable number). */
    fun e164(raw: String?): String? {
        val text = raw?.trim() ?: return null
        if (text.isEmpty() || text.any { it.isLetter() }) return null
        val digits = text.filter { it in '0'..'9' }
        val out = when {
            text.startsWith("+") -> "+$digits"
            text.startsWith("00") -> "+" + digits.drop(2)
            digits.length == LOCAL_DIGITS && digits[0] in '6'..'9' -> "+91$digits"
            digits.length == TRUNK_DIGITS && digits[0] == '0' -> "+91" + digits.drop(1)
            digits.length == COUNTRY_DIGITS && digits.startsWith("91") -> "+$digits"
            else -> return null
        }
        return if (CallWire.E164.matches(out)) out else null
    }

    /** `+91********01`: what the app's own log lines may show of a number (as the server's). */
    fun mask(number: String?): String {
        if (number.isNullOrEmpty()) return ""
        if (number.length <= 5) return "*".repeat(number.length)
        val head = if (number.startsWith("+")) 3 else 0
        return number.take(head) + "*".repeat(number.length - head - 2) + number.takeLast(2)
    }
}

data class CallCan(val place: Boolean, val answer: Boolean, val state: Boolean, val number: Boolean, val notify: Boolean)

sealed interface CallEvent {
    val id: String
    val at: Long

    fun json(): Json.Fields
}

data class StateEvent(
    override val id: String,
    val callId: String?,
    val state: String,
    val number: String?,
    val rings: Int,
    override val at: Long,
) : CallEvent {
    init {
        require(CallWire.EVENT_ID.matches(id) && state in CallWire.STATES) { "not a call state" }
        require(callId == null || CallWire.CALL_ID.matches(callId)) { "not a call id" }
        require(number == null || (state == "ringing" && CallWire.E164.matches(number))) { "a number only while ringing" }
        require(rings in 0..CallRules.MAX_RINGS && at >= 0) { "not a ring count or a time" }
    }

    override fun json(): Json.Fields = Json.obj(
        "id" to id,
        "type" to "call.state",
        "call_id" to callId,
        "state" to state,
        "number_e164" to number,
        "rings" to rings,
        "at" to at,
    )
}

data class ResultEvent(
    override val id: String,
    val commandId: String,
    val callId: String?,
    val command: String,
    val ok: Boolean,
    val code: String,
    override val at: Long,
) : CallEvent {
    init {
        require(CallWire.EVENT_ID.matches(id) && CallWire.COMMAND_ID.matches(commandId)) { "not an id" }
        require(callId == null || CallWire.CALL_ID.matches(callId)) { "not a call id" }
        require(command in CallWire.COMMANDS && CallWire.CODE.matches(code) && at >= 0) { "not a result" }
    }

    override fun json(): Json.Fields = Json.obj(
        "id" to id,
        "type" to "call.result",
        "command_id" to commandId,
        "call_id" to callId,
        "command" to command,
        "ok" to ok,
        "code" to code,
        "at" to at,
    )
}

data class DecisionEvent(override val id: String, val cardId: String, val decision: String, override val at: Long) : CallEvent {
    init {
        require(CallWire.EVENT_ID.matches(id) && CallWire.CARD_ID.matches(cardId)) { "not an id" }
        require(decision == "approve" || decision == "decline") { "not a decision" }
        require(at >= 0) { "not a time" }
    }

    override fun json(): Json.Fields = Json.obj(
        "id" to id,
        "type" to "card.decision",
        "card_id" to cardId,
        "decision" to decision,
        "at" to at,
    )
}

/** The door's answer to a calls request, read; anything unreadable is null (nothing is acted on). */
data class CallsAnswer(
    val key: String,
    val answeringOn: Boolean,
    val afterRings: Int,
    val sendNumber: Boolean,
    val commands: List<Pair<String, String>>,
    val decisions: List<Pair<String, String>>,
)

object CallPayloads {
    private const val EVENT_ID_BYTES = 8

    fun newEventId(random: SecureRandom = SecureRandom()): String {
        val bytes = ByteArray(EVENT_ID_BYTES)
        random.nextBytes(bytes)
        return "pe_" + Door.hex(bytes)
    }

    fun body(appVersion: String, can: CallCan, events: List<CallEvent>, acks: List<String>, wait: Int): ByteArray {
        require(events.size <= CallWire.MAX_EVENTS && acks.size <= CallWire.MAX_ACKS) { "too many in one request" }
        require(acks.all { CallWire.COMMAND_ID.matches(it) } && wait in 0..CallWire.MAX_WAIT_S) { "not acks or a wait" }
        return CanonicalJson.bytes(
            Json.obj(
                "v" to Payloads.V,
                "app_version" to appVersion,
                "can" to Json.obj(
                    "place" to can.place,
                    "answer" to can.answer,
                    "state" to can.state,
                    "number" to can.number,
                    "notify" to can.notify,
                ),
                "events" to events.map { it.json() },
                "acks" to acks,
                "wait" to wait,
            ),
        )
    }

    /** One event as one line, for the app's queue of events not yet taken. */
    fun encode(event: CallEvent): String = CanonicalJson.write(event.json())

    fun decode(line: String): CallEvent? {
        val v = JsonRead.parseOrNull(line) as? Json.Fields ?: return null
        val id = v.textOf("id") ?: return null
        val at = v.longOf("at") ?: return null
        return try {
            when (v.textOf("type")) {
                "call.state" -> StateEvent(id, v.textOf("call_id"), v.textOf("state") ?: return null, v.textOf("number_e164"), (v.longOf("rings") ?: return null).toInt(), at)
                "call.result" -> ResultEvent(id, v.textOf("command_id") ?: return null, v.textOf("call_id"), v.textOf("command") ?: return null, v.boolOf("ok") ?: return null, v.textOf("code") ?: return null, at)
                "card.decision" -> DecisionEvent(id, v.textOf("card_id") ?: return null, v.textOf("decision") ?: return null, at)
                else -> null
            }
        } catch (e: IllegalArgumentException) {
            null
        }
    }

    fun answer(text: String): CallsAnswer? {
        val v = JsonRead.parseOrNull(text) as? Json.Fields ?: return null
        if (v.longOf("v") != 1L) return null
        val key = v.textOf("key")?.takeIf { CallWire.isKey(it) } ?: return null
        val answering = v.field("answering") as? Json.Fields ?: return null
        val commands = (v.field("commands") as? Json.Items)?.items.orEmpty().mapNotNull { item ->
            val c = item as? Json.Fields ?: return@mapNotNull null
            val body = c.textOf("body") ?: return@mapNotNull null
            val sig = c.textOf("sig") ?: return@mapNotNull null
            body to sig
        }
        val decisions = (v.field("decisions") as? Json.Items)?.items.orEmpty().mapNotNull { item ->
            val d = item as? Json.Fields ?: return@mapNotNull null
            (d.textOf("card_id") ?: return@mapNotNull null) to (d.textOf("outcome") ?: return@mapNotNull null)
        }
        return CallsAnswer(
            key = key,
            answeringOn = answering.boolOf("on") ?: false,
            afterRings = (answering.longOf("after_rings") ?: 5L).toInt().coerceIn(1, CallRules.MAX_RINGS),
            sendNumber = answering.boolOf("number") ?: false,
            commands = commands,
            decisions = decisions,
        )
    }
}

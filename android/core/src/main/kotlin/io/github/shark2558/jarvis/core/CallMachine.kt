// android/core/src/main/kotlin/io/github/shark2558/jarvis/core/CallMachine.kt
// R18 D: what the phone reports about calls, from the three states Android gives an ordinary app
// (TelephonyManager's IDLE, RINGING, OFFHOOK in the PHONE_STATE broadcast). Only JARVIS's calls are
// reported, and incoming calls only while answering missed calls is on: his own calls are none of
// the cloud's business.
//
//   a dial JARVIS placed, then OFFHOOK      -> dialing (call id of the dial)
//   ... then IDLE                           -> ended
//   RINGING while answering is on           -> ringing (no call id; the number when it may go)
//   ... then OFFHOOK                        -> active (the call id if JARVIS answered it, else none:
//                                              he picked it up himself)
//   ... then IDLE                           -> ended (missed, declined or finished)
//
// Android tells an ordinary app nothing about when the other side picks up an outgoing call
// (that needs READ_PRECISE_PHONE_STATE, a system permission): "dialing" stays until the call ends,
// and the call desk's voice detector tells the engine when they speak. A dial is matched to the
// next OFFHOOK only within DIAL_MATCH_MS; an OFFHOOK later than that is his own call. The state is
// kept between broadcasts as one line (`encode`), because the app's process may die in between.
package io.github.shark2558.jarvis.core

enum class PhonePhase { IDLE, RINGING, OFFHOOK }

/** One report the app turns into a `StateEvent` (adding its id and time). */
data class StateReport(val callId: String?, val state: String, val number: String?, val rings: Int)

data class MachineStep(val machine: CallMachine, val reports: List<StateReport>)

data class CallMachine(
    val phase: PhonePhase = PhonePhase.IDLE,
    val callId: String? = null,
    val reporting: Boolean = false,
    val ringStartMs: Long = 0L,
    val number: String? = null,
    val pendingDial: String? = null,
    val pendingDialMs: Long = 0L,
) {
    /** JARVIS placed a dial for this call: the next OFFHOOK is it. */
    fun dialPlaced(callId: String, nowMs: Long): CallMachine {
        require(CallWire.CALL_ID.matches(callId)) { "not a call id" }
        return copy(pendingDial = callId, pendingDialMs = nowMs)
    }

    /** JARVIS answered the ringing call: it becomes this call. */
    fun answered(callId: String): CallMachine {
        require(CallWire.CALL_ID.matches(callId)) { "not a call id" }
        return if (phase == PhonePhase.RINGING) copy(callId = callId, reporting = true) else this
    }

    val ringing: Boolean get() = phase == PhonePhase.RINGING

    fun rings(nowMs: Long): Int = if (ringing) CallRules.rings(ringStartMs, nowMs) else 0

    /** The ringing report at ring `n` (the answering policy's moment), if it is still ringing. */
    fun ringAt(nowMs: Long, sendNumber: Boolean): StateReport? =
        if (ringing && reporting) StateReport(callId, "ringing", number.takeIf { sendNumber }, rings(nowMs)) else null

    fun onPhone(next: PhonePhase, nowMs: Long, answeringOn: Boolean, incoming: String?, sendNumber: Boolean): MachineStep {
        val known = CallRules.e164(incoming)
        return when (phase) {
            PhonePhase.IDLE -> fromIdle(next, nowMs, answeringOn, known, sendNumber)
            PhonePhase.RINGING -> fromRinging(next, known)
            PhonePhase.OFFHOOK -> fromOffhook(next)
        }
    }

    private fun fromIdle(next: PhonePhase, nowMs: Long, answeringOn: Boolean, known: String?, sendNumber: Boolean): MachineStep =
        when (next) {
            PhonePhase.IDLE -> MachineStep(this, emptyList())
            PhonePhase.RINGING -> {
                val m = CallMachine(PhonePhase.RINGING, null, answeringOn, nowMs, known, pendingDial, pendingDialMs)
                val out = if (answeringOn) listOf(StateReport(null, "ringing", known.takeIf { sendNumber }, 1)) else emptyList()
                MachineStep(m, out)
            }
            PhonePhase.OFFHOOK -> {
                val dial = pendingDial?.takeIf { nowMs - pendingDialMs in 0L..DIAL_MATCH_MS }
                if (dial == null) {
                    MachineStep(CallMachine(PhonePhase.OFFHOOK), emptyList()) // his own call
                } else {
                    MachineStep(CallMachine(PhonePhase.OFFHOOK, dial, true), listOf(StateReport(dial, "dialing", null, 0)))
                }
            }
        }

    private fun fromRinging(next: PhonePhase, known: String?): MachineStep = when (next) {
        // Android sends RINGING twice (with the number only to an app that may read the call log)
        PhonePhase.RINGING -> MachineStep(if (number == null && known != null) copy(number = known) else this, emptyList())
        PhonePhase.OFFHOOK -> {
            val out = if (reporting) listOf(StateReport(callId, "active", null, 0)) else emptyList()
            MachineStep(copy(phase = PhonePhase.OFFHOOK, number = null), out)
        }
        PhonePhase.IDLE -> {
            val out = if (reporting) listOf(StateReport(callId, "ended", null, 0)) else emptyList()
            MachineStep(CallMachine(pendingDial = pendingDial, pendingDialMs = pendingDialMs), out)
        }
    }

    private fun fromOffhook(next: PhonePhase): MachineStep = when (next) {
        PhonePhase.IDLE -> {
            val out = if (reporting) listOf(StateReport(callId, "ended", null, 0)) else emptyList()
            MachineStep(CallMachine(), out)
        }
        else -> MachineStep(this, emptyList()) // a waiting call during a call: nothing new for JARVIS
    }

    /** One line for the app's private preferences (the number only while it rings). */
    fun encode(): String = listOf(
        phase.name,
        callId.orEmpty(),
        if (reporting) "1" else "0",
        ringStartMs.toString(),
        number.orEmpty(),
        pendingDial.orEmpty(),
        pendingDialMs.toString(),
    ).joinToString("|")

    companion object {
        const val DIAL_MATCH_MS = 60_000L
        private const val PARTS = 7

        fun phaseOf(androidState: String?): PhonePhase? = when (androidState) {
            "IDLE" -> PhonePhase.IDLE
            "RINGING" -> PhonePhase.RINGING
            "OFFHOOK" -> PhonePhase.OFFHOOK
            else -> null
        }

        /** The line `encode` wrote; anything unreadable is a fresh, idle machine. */
        fun decode(line: String?): CallMachine {
            val p = line?.split("|") ?: return CallMachine()
            if (p.size != PARTS) return CallMachine()
            return try {
                CallMachine(
                    phase = PhonePhase.valueOf(p[0]),
                    callId = p[1].ifEmpty { null }?.takeIf { CallWire.CALL_ID.matches(it) },
                    reporting = p[2] == "1",
                    ringStartMs = p[3].toLong(),
                    number = p[4].ifEmpty { null }?.takeIf { CallWire.E164.matches(it) },
                    pendingDial = p[5].ifEmpty { null }?.takeIf { CallWire.CALL_ID.matches(it) },
                    pendingDialMs = p[6].toLong(),
                )
            } catch (e: IllegalArgumentException) {
                CallMachine()
            }
        }
    }
}

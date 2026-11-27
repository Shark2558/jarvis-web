// android/core/src/test/kotlin/io/github/shark2558/jarvis/core/CallMachineTest.kt
// R18 D: what the phone reports from Android's three call states. JARVIS's own dial is reported
// (dialing, ended); his own calls are not; an incoming call only while answering is on, its number
// only when the cloud asked for it; Android's second RINGING broadcast brings the number; a call he
// picks up himself is "active" with no call id, one JARVIS answered carries its call id; the state
// survives the process dying between broadcasts.
package io.github.shark2558.jarvis.core

private const val CALL = "call_000000000001"
private const val NUMBER = "+919000000001"

private fun CallMachine.go(next: PhonePhase, nowMs: Long, on: Boolean = false, incoming: String? = null, send: Boolean = false): MachineStep =
    onPhone(next, nowMs, on, incoming, send)

fun callMachineCases(): List<Case> = cases(
    "call machine",
    "a dial JARVIS placed is dialing at OFFHOOK and ended at IDLE" to {
        val placed = CallMachine().dialPlaced(CALL, 1_000L)
        val off = placed.go(PhonePhase.OFFHOOK, 3_000L)
        same(listOf(StateReport(CALL, "dialing", null, 0)), off.reports, "dialing")
        val idle = off.machine.go(PhonePhase.IDLE, 60_000L)
        same(listOf(StateReport(CALL, "ended", null, 0)), idle.reports, "ended")
        same(CallMachine(), idle.machine, "back to idle")
    },
    "his own call, or an OFFHOOK long after a dial, is not reported" to {
        val own = CallMachine().go(PhonePhase.OFFHOOK, 1_000L)
        yes(own.reports.isEmpty() && own.machine.go(PhonePhase.IDLE, 2_000L).reports.isEmpty(), "his own call")
        val late = CallMachine().dialPlaced(CALL, 0L).go(PhonePhase.OFFHOOK, CallMachine.DIAL_MATCH_MS + 1)
        yes(late.reports.isEmpty(), "too late to be the dial")
    },
    "an incoming call is reported only while answering is on" to {
        val off = CallMachine().go(PhonePhase.RINGING, 0L, on = false, incoming = "09000000001")
        yes(off.reports.isEmpty(), "answering off: nothing")
        yes(off.machine.go(PhonePhase.IDLE, 5_000L).reports.isEmpty(), "and nothing when it stops")
        val on = CallMachine().go(PhonePhase.RINGING, 0L, on = true, incoming = "09000000001", send = false)
        same(listOf(StateReport(null, "ringing", null, 1)), on.reports, "ringing, no number unless asked")
        val asked = CallMachine().go(PhonePhase.RINGING, 0L, on = true, incoming = "09000000001", send = true)
        same(listOf(StateReport(null, "ringing", NUMBER, 1)), asked.reports, "ringing with its number")
    },
    "Android's second RINGING brings the number for ring N" to {
        val first = CallMachine().go(PhonePhase.RINGING, 0L, on = true, incoming = null, send = true)
        same(listOf(StateReport(null, "ringing", null, 1)), first.reports, "the first has none")
        val second = first.machine.go(PhonePhase.RINGING, 200L, on = true, incoming = "+91 90000 00001", send = true)
        yes(second.reports.isEmpty(), "no second report")
        same(StateReport(null, "ringing", NUMBER, 5), second.machine.ringAt(12_000L, sendNumber = true), "ring five, with the number")
        same(StateReport(null, "ringing", null, 5), second.machine.ringAt(12_000L, sendNumber = false), "without, when not asked")
    },
    "picked up by him is active with no id; answered by JARVIS carries the call id" to {
        val ringing = CallMachine().go(PhonePhase.RINGING, 0L, on = true).machine
        same(listOf(StateReport(null, "active", null, 0)), ringing.go(PhonePhase.OFFHOOK, 4_000L).reports, "he picked up")
        val jarvis = ringing.answered(CALL).go(PhonePhase.OFFHOOK, 15_000L)
        same(listOf(StateReport(CALL, "active", null, 0)), jarvis.reports, "JARVIS answered")
        same(listOf(StateReport(CALL, "ended", null, 0)), jarvis.machine.go(PhonePhase.IDLE, 90_000L).reports, "then ended")
        same(null, jarvis.machine.number, "the number is not kept once it stops ringing")
    },
    "a missed call ends the ringing, and an answer for a call no longer ringing changes nothing" to {
        val ringing = CallMachine().go(PhonePhase.RINGING, 0L, on = true).machine
        same(listOf(StateReport(null, "ended", null, 0)), ringing.go(PhonePhase.IDLE, 20_000L).reports, "missed")
        same(CallMachine(), CallMachine().answered(CALL), "not ringing: nothing to answer")
        same(null, CallMachine().ringAt(0L, true), "no ring when idle")
    },
    "a waiting call during a call is nothing new" to {
        val inCall = CallMachine().dialPlaced(CALL, 0L).go(PhonePhase.OFFHOOK, 1_000L).machine
        val waiting = inCall.go(PhonePhase.RINGING, 5_000L, on = true, incoming = "09000000001")
        yes(waiting.reports.isEmpty() && waiting.machine == inCall, "unchanged")
    },
    "the machine survives the process dying between broadcasts" to {
        val ringing = CallMachine().dialPlaced(CALL, 7L).go(PhonePhase.RINGING, 1_000L, on = true, incoming = "09000000001").machine
        same(ringing, CallMachine.decode(ringing.encode()), "round trip")
        same(CallMachine(), CallMachine.decode(null), "nothing kept")
        same(CallMachine(), CallMachine.decode("RINGING|x"), "garbage")
        same(CallMachine(), CallMachine.decode("HELD||0|0|||0"), "an unknown phase")
        same(PhonePhase.OFFHOOK, CallMachine.phaseOf("OFFHOOK"), "Android's word")
        same(null, CallMachine.phaseOf("DIALING"), "not Android's word")
    },
)

// android/core/src/test/kotlin/io/github/shark2558/jarvis/core/RulesTest.kt
// R7 D8, D10, D16, D19, D24: the launch words, the notification channels by tag, the inbox's
// "seen" list and file rules, and the SOS text message (fixed sentences, never a model).
package io.github.shark2558.jarvis.core

import java.time.OffsetDateTime
import java.time.ZoneId

private const val HOST = "jarvis.invalid"

fun launchCases(): List<Case> = cases(
    "launch",
    "exactly the four launch words of the contract" to {
        same(listOf("talk", "look", "sos", "shared"), Launch.WORDS, "the words")
    },
    "the icon always opens /?source=app" to {
        same("https://jarvis.invalid/?source=app", Launch.iconUrl(HOST), "icon address")
    },
    "a screen launch adds one word from the allow-list, and nothing else" to {
        for (word in Launch.WORDS) {
            same("https://jarvis.invalid/?source=app&do=$word", Launch.screenUrl(HOST, word), "word $word")
        }
        same(Launch.iconUrl(HOST), Launch.screenUrl(HOST, "start_mic"), "an unknown word opens the icon's address")
        same(Launch.iconUrl(HOST), Launch.screenUrl(HOST, "talk&open=vault"), "a word cannot carry more words")
        same(Launch.iconUrl(HOST), Launch.screenUrl(HOST, null), "no word")
    },
    "only this app's own actions map to words" to {
        same("talk", Launch.wordForAction("io.github.shark2558.jarvis.action.TALK"), "TALK")
        same("look", Launch.wordForAction("io.github.shark2558.jarvis.action.LOOK"), "LOOK")
        same("sos", Launch.wordForAction("io.github.shark2558.jarvis.action.SOS"), "SOS")
        same(null, Launch.wordForAction("android.intent.action.VIEW"), "a VIEW intent")
        same(null, Launch.wordForAction("io.github.shark2558.jarvis.action.UNLOCK"), "an unknown action")
        same(null, Launch.wordForAction(null), "no action")
    },
    "the address must be a plain host name" to {
        yes(Launch.isHost("jarvis.invalid"), "the placeholder")
        yes(Launch.isHost("a-b.example.com"), "a name with a hyphen")
        for (bad in listOf("", "jarvis", "https://jarvis.invalid", "jarvis.invalid/x", "jarvis.invalid:8443",
            "Jarvis.invalid", "-a.example.com", "a..example.com", "192.168.1.2", " jarvis.invalid", "a b.example.com")) {
            yes(!Launch.isHost(bad), "not a host: '$bad'")
        }
        refuses<IllegalArgumentException>("a URL as the host") { Launch.iconUrl("http://jarvis.invalid") }
    },
)

fun channelCases(): List<Case> = cases(
    "channels",
    "urgent kinds go to Urgent" to {
        for (kind in listOf("home_intruder", "home_hazard", "disaster_alert", "sos_sent", "phone_linked")) {
            same(AlertChannel.URGENT, Channels.forTag(kind), kind)
        }
    },
    "nudge kinds go to Nudges, everything else to Alerts" to {
        same(AlertChannel.NUDGES, Channels.forTag("nudge_hydrate"), "nudge")
        same(AlertChannel.ALERTS, Channels.forTag("brief_ready"), "an ordinary kind")
        same(AlertChannel.ALERTS, Channels.forTag("approval_waiting"), "approvals")
    },
    "a tag it cannot read goes to Alerts" to {
        for (tag in listOf(null, "", "#", "SOS_SENT", "sos sent", "x".repeat(80), "p#https://jarvis.invalid#0123")) {
            same(AlertChannel.ALERTS, Channels.forTag(tag), "tag '$tag'")
        }
    },
    "the kind is read from the end of Chrome's own tag form" to {
        same("sos_sent", Channels.kindFromTag("p#https://jarvis.invalid#1sos_sent"), "with the '1' marker")
        same(AlertChannel.URGENT, Channels.forTag("p#https://jarvis.invalid#1home_hazard"), "urgent through Chrome's form")
        same(AlertChannel.NUDGES, Channels.forTag("p#https://jarvis.invalid#nudge_focus"), "without the marker")
    },
    "three channels with their own ids" to {
        same(3, AlertChannel.entries.size, "three channels")
        same(3, AlertChannel.entries.map { it.id }.toSet().size, "distinct ids")
    },
)

fun inboxCases(): List<Case> = cases(
    "inbox",
    "the seen list keeps each file once, by its SHA-256" to {
        val a = "a".repeat(64)
        val b = "b".repeat(64)
        val seen = SeenList.decode(null).adding(a).adding(a).adding(b)
        yes(a in seen && b in seen, "both are seen")
        same(2, seen.size, "a file is kept once")
        val back = SeenList.decode(seen.encode())
        yes(a in back && b in back, "the list survives a restart")
    },
    "the seen list ignores junk and keeps only the newest entries" to {
        val junk = SeenList.decode("not a hash\n" + "c".repeat(64) + "\n\n")
        same(1, junk.size, "junk lines are ignored")
        var list = SeenList.decode(null, cap = 3)
        for (ch in listOf('1', '2', '3', '4')) list = list.adding(ch.toString().repeat(64))
        same(3, list.size, "the cap holds")
        yes("1".repeat(64) !in list && "4".repeat(64) in list, "the oldest is dropped")
    },
    "only PDF, JPEG and PNG of at most 10 MB, oldest first, three a run" to {
        val files = listOf(
            InboxRules.Candidate("1", "b.pdf", "application/pdf", 2_000, 20),
            InboxRules.Candidate("2", "a.png", "image/png", 3_000, 10),
            InboxRules.Candidate("3", "x.exe", "application/octet-stream", 10, 5),
            InboxRules.Candidate("4", "big.pdf", "application/pdf", InboxRules.MAX_BYTES + 1, 1),
            InboxRules.Candidate("5", "empty.jpg", "image/jpeg", 0, 2),
        )
        same(listOf("2", "1"), InboxRules.order(files).map { it.id }, "eligible, oldest first")
        same(3, InboxRules.PER_RUN, "three a run")
    },
    "the file's own first bytes decide its type" to {
        same("application/pdf", InboxRules.sniff("%PDF-1.4\n".toByteArray()), "pdf")
        same("image/png", InboxRules.sniff(byteArrayOf(0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A)), "png")
        same("image/jpeg", InboxRules.sniff(byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 0xFF.toByte(), 0xE0.toByte())), "jpeg")
        same(null, InboxRules.sniff("MZ\u0090\u0000".toByteArray()), "an executable")
        same(null, InboxRules.sniff(ByteArray(0)), "an empty file")
    },
    "a file's name is cleaned before it is sent" to {
        same("report.pdf", InboxRules.cleanName("../x/report.pdf"), "no folders")
        same("ab.pdf", InboxRules.cleanName("a\u0000\nb.pdf"), "no control characters")
        same("document", InboxRules.cleanName("  "), "an empty name")
        same(120, InboxRules.cleanName("n".repeat(500)).length, "at most 120 characters")
    },
)

fun smsCases(): List<Case> = cases(
    "sms",
    "the SOS text with a location is the fixed sentence" to {
        val fixAt = OffsetDateTime.parse("2026-11-13T14:05:00+05:30").toEpochSecond()
        val fix = Fix(latE6 = 12_971_599, lonE6 = 77_594_566, accuracyM = 20, ageS = 8, atEpochS = fixAt)
        val text = SosText.message("Sample Owner", fix, ZoneId.of("Asia/Kolkata"))
        same(
            "SOS from Sample Owner: I need help. My location at 14:05: " +
                "https://maps.google.com/?q=12.971599,77.594566 (within about 20 m). Sent by my JARVIS assistant.",
            text,
            "message",
        )
    },
    "without a location the text says so" to {
        same(
            "SOS from Sample Owner: I need help. My location is not available. Sent by my JARVIS assistant.",
            SosText.message("Sample Owner", null, ZoneId.of("Asia/Kolkata")),
            "no location",
        )
        same(
            "SOS: I need help. My location is not available. Sent by my JARVIS assistant.",
            SosText.message(null, null, ZoneId.of("Asia/Kolkata")),
            "no label",
        )
    },
    "degrees are written from micro-degrees with six decimals, south and west too" to {
        same("-0.000001", SosText.degrees(-1), "just south of the equator")
        same("12.000000", SosText.degrees(12_000_000), "whole degrees")
        same("-122.419416", SosText.degrees(-122_419_416), "west")
    },
    "a label loses control characters and stays short" to {
        same("ab", SosText.cleanLabel("a\nb"), "no newline")
        same(40, SosText.cleanLabel("x".repeat(90)).length, "at most 40")
    },
    "the SMS address holds every usable number once" to {
        same("smsto:5550100;+5550101", SosText.smsUri(listOf("555 0100", "+555 0101", "555-0100", "call me")), "numbers")
        same(null, SosText.smsUri(listOf("none")), "no number")
    },
)

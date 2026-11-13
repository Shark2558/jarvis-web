// android/core/src/test/kotlin/io/github/shark2558/jarvis/core/RepliesTest.kt
// R7 D6, D16, D19: what the door's answers mean (distinct plain sentences, the clock hint), which
// answers a job retries, when the app says it needs linking again, and when the folder marks a
// file handled (only on success or a refusal that waiting cannot change).
package io.github.shark2558.jarvis.core

fun replyCases(): List<Case> = cases(
    "replies",
    "every answer the door gives has its own plain sentence" to {
        val statuses = listOf(401, 403, 404, 413, 429, 500, 503, 408, 400)
        val sentences = statuses.mapNotNull { Replies.explain(it, null)?.sentence }
        same(statuses.size, sentences.size, "each status is a refusal")
        same(8, sentences.toSet().size, "eight different sentences for nine statuses (500 and 503 share one)")
        same(Refusal.SERVER, Replies.explain(500, null), "500")
        same(Refusal.SERVER, Replies.explain(503, null), "503")
        same(Refusal.TOO_MANY, Replies.explain(429, null), "429")
        same(Refusal.TOO_BIG, Replies.explain(413, null), "413")
        same(Refusal.FORBIDDEN, Replies.explain(403, null), "403")
        same(Refusal.NOT_FOUND, Replies.explain(404, null), "404")
        yes(Replies.explain(200, null) == null && Replies.explain(204, null) == null, "2xx is no refusal")
        yes(Refusal.entries.all { it.sentence.contains("Sir") && it.sentence.endsWith(".") }, "plain and polite")
    },
    "a 401 with a clock more than 120 seconds off says so; within it, it is the link" to {
        same(Refusal.CLOCK, Replies.explain(401, 121L), "121 s ahead")
        same(Refusal.CLOCK, Replies.explain(401, -300L), "300 s behind")
        same(Refusal.UNKNOWN_PHONE, Replies.explain(401, 120L), "exactly 120 s is not the clock")
        same(Refusal.UNKNOWN_PHONE, Replies.explain(401, null), "no Date header")
        same(Refusal.FORBIDDEN, Replies.explain(403, 900L), "the clock hint is for 401 only")
        same(-90L, Replies.skewSeconds(1_000_000L, 910_000L), "phone ahead by 90 s")
        same(null, Replies.skewSeconds(1_000_000L, 0L), "no server time")
    },
    "jobs retry only 408, 425, 429 and 5xx" to {
        for (status in listOf(408, 425, 429, 500, 502, 503, 504)) yes(Replies.worthRetry(status), "$status retries")
        for (status in listOf(400, 401, 403, 404, 413, 415, 422, 200)) yes(!Replies.worthRetry(status), "$status stops")
    },
    "three 401s in a row mean linking again; a clock fault or a success does not" to {
        var n = 0
        n = Replies.strikes(n, Replies.explain(401, null))
        n = Replies.strikes(n, Replies.explain(401, null))
        yes(!Replies.needsLinking(n), "two are not enough")
        n = Replies.strikes(n, Replies.explain(401, 500L))
        yes(!Replies.needsLinking(n), "a clock fault does not count")
        n = Replies.strikes(n, Replies.explain(429, null))
        same(2, n, "other refusals leave the count")
        n = Replies.strikes(n, Replies.explain(401, null))
        yes(Replies.needsLinking(n), "the third 401")
        same(0, Replies.strikes(n, null), "a success clears it")
    },
    "the folder marks a file handled only on success or a refusal for good" to {
        same(InboxFate.SENT, Inbox.fate(200), "200")
        same(InboxFate.SENT, Inbox.fate(201), "201")
        for (status in listOf(400, 413, 415, 422)) same(InboxFate.REFUSED_FOR_GOOD, Inbox.fate(status), "$status")
        for (status in listOf(401, 403, 404, 408, 425, 429, 500, 503)) same(InboxFate.LATER, Inbox.fate(status), "$status waits")
    },
)

// android/app/src/main/java/io/github/shark2558/jarvis/calls/CallsWake.kt
// R18 D: the cloud's doorbell. The cloud cannot reach the phone except by Web Push, which Chrome
// hands to the app's notification service (R7 D10); a push of the kind `call_command` means "a
// signed call command is waiting at the door". The kind is read from the notification's tag the way
// core's Channels reads every alert's kind.
package io.github.shark2558.jarvis.calls

import io.github.shark2558.jarvis.core.Channels

object CallsWake {
    const val KIND = "call_command"

    fun isDoorbell(platformTag: String?): Boolean = Channels.kindFromTag(platformTag) == KIND
}

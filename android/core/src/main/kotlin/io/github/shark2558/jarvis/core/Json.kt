// android/core/src/main/kotlin/io/github/shark2558/jarvis/core/Json.kt
// R7 D6, D24: the ONE byte form of every body the phone signs (phone-contract.md section 4),
// equal byte for byte to the server's `contract.canonical_json` (Python's json.dumps with
// ensure_ascii=False and no spaces): keys in the order given, integers only, `"` `\` and the
// control characters escaped, every other character written as itself in UTF-8.
package io.github.shark2558.jarvis.core

/** A payload value: only the shapes the door's bodies use (no fractions: D6). */
sealed interface Json {
    data object Null : Json

    data class Bool(val value: Boolean) : Json

    data class Num(val value: Long) : Json

    data class Text(val value: String) : Json

    data class Items(val items: List<Json>) : Json

    data class Fields(val fields: List<Pair<String, Json>>) : Json {
        init {
            require(fields.map { it.first }.toSet().size == fields.size) { "a key appears twice" }
        }
    }

    companion object {
        fun obj(vararg fields: Pair<String, Any?>): Fields = Fields(fields.map { (k, v) -> k to of(v) })

        fun of(value: Any?): Json = when (value) {
            null -> Null
            is Json -> value
            is Boolean -> Bool(value)
            is Int -> Num(value.toLong())
            is Long -> Num(value)
            is String -> Text(value)
            is List<*> -> Items(value.map { of(it) })
            else -> throw IllegalArgumentException("not a payload value: ${value::class.simpleName}")
        }
    }
}

object CanonicalJson {
    private const val HEX = "0123456789abcdef"

    fun write(value: Json): String {
        val out = StringBuilder()
        append(out, value)
        return out.toString()
    }

    fun bytes(value: Json): ByteArray = write(value).toByteArray(Charsets.UTF_8)

    private fun append(out: StringBuilder, value: Json) {
        when (value) {
            is Json.Null -> out.append("null")
            is Json.Bool -> out.append(if (value.value) "true" else "false")
            is Json.Num -> out.append(value.value)
            is Json.Text -> text(out, value.value)
            is Json.Items -> {
                out.append('[')
                value.items.forEachIndexed { i, item ->
                    if (i > 0) out.append(',')
                    append(out, item)
                }
                out.append(']')
            }
            is Json.Fields -> {
                out.append('{')
                value.fields.forEachIndexed { i, field ->
                    if (i > 0) out.append(',')
                    text(out, field.first)
                    out.append(':')
                    append(out, field.second)
                }
                out.append('}')
            }
        }
    }

    private fun text(out: StringBuilder, s: String) {
        out.append('"')
        var i = 0
        while (i < s.length) {
            val c = s[i]
            when {
                c == '"' -> out.append("\\\"")
                c == '\\' -> out.append("\\\\")
                c == '\n' -> out.append("\\n")
                c == '\r' -> out.append("\\r")
                c == '\t' -> out.append("\\t")
                c == '\b' -> out.append("\\b")
                c == '\u000C' -> out.append("\\f")
                c.code < 0x20 -> {
                    out.append("\\u00")
                    out.append(HEX[c.code shr 4])
                    out.append(HEX[c.code and 0xF])
                }
                Character.isHighSurrogate(c) -> {
                    require(i + 1 < s.length && Character.isLowSurrogate(s[i + 1])) {
                        "a lone surrogate has no UTF-8 form"
                    }
                    out.append(c)
                    out.append(s[i + 1])
                    i += 1
                }
                Character.isLowSurrogate(c) -> throw IllegalArgumentException("a lone surrogate has no UTF-8 form")
                else -> out.append(c)
            }
            i += 1
        }
        out.append('"')
    }
}

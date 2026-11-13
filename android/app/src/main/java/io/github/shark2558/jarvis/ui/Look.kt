// android/app/src/main/java/io/github/shark2558/jarvis/ui/Look.kt
// R7 D0: the native screens use the console's own three open-licensed fonts (assets/fonts, with
// their SIL OFL licences beside them): Orbitron for titles, Share Tech Mono for numbers and
// codes, Rajdhani for everything else. A view's tag picks the face.
package io.github.shark2558.jarvis.ui

import android.content.Context
import android.graphics.Typeface
import android.view.View
import android.view.ViewGroup
import android.widget.TextView

object Look {
    private val FILES = mapOf(
        "title" to "fonts/orbitron-700.ttf",
        "mono" to "fonts/share-tech-mono-400.ttf",
        "strong" to "fonts/rajdhani-700.ttf",
        "body" to "fonts/rajdhani-500.ttf",
    )
    private var faces: Map<String, Typeface>? = null

    fun fonts(context: Context, root: View) {
        walk(root, load(context))
    }

    private fun load(context: Context): Map<String, Typeface> {
        val known = faces
        if (known != null) return known
        val loaded = HashMap<String, Typeface>()
        for ((tag, file) in FILES) {
            try {
                loaded[tag] = Typeface.createFromAsset(context.assets, file)
            } catch (e: RuntimeException) {
                // a missing font leaves the system's own face: the screen still works
            }
        }
        faces = loaded
        return loaded
    }

    private fun walk(view: View, loaded: Map<String, Typeface>) {
        if (view is TextView) {
            val tag = view.tag as? String
            val face = loaded[tag ?: "body"] ?: loaded["body"]
            if (face != null) view.typeface = face
        }
        if (view is ViewGroup) {
            for (i in 0 until view.childCount) walk(view.getChildAt(i), loaded)
        }
    }
}

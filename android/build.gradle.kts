// android/build.gradle.kts -- R7 D23 (I0): the pinned plugins, declared once and applied by the
// modules Part E writes. `resolveDependencies` resolves every resolvable configuration of every
// project, so CI's first step proves each pin exists before anything is built.
plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.jvm) apply false
}

tasks.register("resolveDependencies") {
    notCompatibleWithConfigurationCache("resolves every project's configurations on purpose")
    doLast {
        allprojects.forEach { project ->
            project.configurations.filter { it.isCanBeResolved }.forEach { it.resolve() }
        }
        println("every dependency resolved")
    }
}

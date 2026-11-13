// android/settings.gradle.kts -- R7 D23, D24 (I0): the Android project's settings. Part E adds
// include(":core", ":app") with the two modules; until then CI proves the wrapper and that every
// pinned plugin resolves from Google's Maven and the Gradle Plugin Portal.
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "jarvis-android"

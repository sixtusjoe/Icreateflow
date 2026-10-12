import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
}

val appVersion = Properties().apply { rootProject.file("version.properties").inputStream().use(::load) }

// The one key every build is signed with, kept outside the repo. An update
// only installs over a build signed with the same key, so this file — and
// the keystore it names — must survive every Mac move: lose it and every
// installed phone has to uninstall and start again. Without it, builds fall
// back to this Mac's own debug key and can't update anyone else's install.
val signing = Properties().apply {
    val f = File(System.getProperty("user.home"), ".icreateflow/android-signing.properties")
    if (f.isFile) f.inputStream().use(::load)
}

android {
    namespace = "com.icreateflow.companion"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.icreateflow.companion"
        minSdk = 26
        targetSdk = 35
        versionCode = appVersion.getProperty("code").toInt()
        versionName = appVersion.getProperty("name")
    }

    signingConfigs {
        if (signing.getProperty("storeFile") != null) create("icreateflow") {
            storeFile = File(signing.getProperty("storeFile"))
            storePassword = signing.getProperty("storePassword")
            keyAlias = signing.getProperty("keyAlias")
            keyPassword = signing.getProperty("keyPassword")
        }
    }

    buildTypes {
        signingConfigs.findByName("icreateflow")?.let { key ->
            getByName("debug").signingConfig = key
            getByName("release").signingConfig = key
        }
        debug {
            // The review build talks to the backend on the developer's Mac,
            // reached over the USB cable with `adb reverse tcp:8000 tcp:8000`.
            // No shared Wi-Fi involved.
            buildConfigField("String", "API_BASE", "\"http://127.0.0.1:8000\"")
            applicationIdSuffix = ".dev"
        }
        release {
            buildConfigField("String", "API_BASE", "\"https://icreateflow.com\"")
            isMinifyEnabled = false
        }
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.12.01")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.core:core-splashscreen:1.0.1")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    debugImplementation("androidx.compose.ui:ui-tooling")
}

package com.icreateflow.companion

import android.app.Application
import android.content.Context

/**
 * Holds the signed-in session. The token lives in the app's private
 * preferences — readable by nothing else on the phone — and is dropped the
 * moment the server says it is no longer good.
 */
class CompanionApp : Application() {
    val session by lazy { Session(getSharedPreferences("session", Context.MODE_PRIVATE)) }

    override fun onCreate() {
        super.onCreate()
        session.server?.let { com.icreateflow.companion.data.Api.base = it }
    }
}

class Session(private val prefs: android.content.SharedPreferences) {
    var token: String?
        get() = prefs.getString("token", null)
        set(v) = prefs.edit().apply { if (v == null) remove("token") else putString("token", v) }.apply()

    var name: String?
        get() = prefs.getString("name", null)
        set(v) = prefs.edit().apply { if (v == null) remove("name") else putString("name", v) }.apply()

    var email: String?
        get() = prefs.getString("email", null)
        set(v) = prefs.edit().apply { if (v == null) remove("email") else putString("email", v) }.apply()

    /** The TikTok account this phone is signed in as — kept across sign-outs. */
    var tiktokHandle: String?
        get() = prefs.getString("tiktok_handle", null)
        set(v) = prefs.edit().apply { if (v.isNullOrBlank()) remove("tiktok_handle") else putString("tiktok_handle", v) }.apply()

    /**
     * This install's id — how the server tells this phone from any other the
     * same person signs in on. Made once, kept across sign-outs, never shown.
     */
    val deviceId: String
        get() = prefs.getString("device_id", null) ?: ("phone-" + java.util.UUID.randomUUID().toString())
            .also { prefs.edit().putString("device_id", it).apply() }

    /** The server picked on the sign-in screen, or null for the build's own. Kept across sign-outs. */
    var server: String?
        get() = prefs.getString("server", null)
        set(v) = prefs.edit().apply { if (v == null) remove("server") else putString("server", v) }.apply()

    fun clear() {
        val handle = tiktokHandle
        val device = deviceId
        val server = server
        prefs.edit().clear().apply()
        tiktokHandle = handle
        this.server = server
        prefs.edit().putString("device_id", device).apply()
    }
}

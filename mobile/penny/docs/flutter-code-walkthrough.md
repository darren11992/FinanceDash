# Flutter Code Walkthrough — Penny Project

**Date:** 2026-03-23
**Context:** Sprint 2 Week 2 complete. Walking through the full Flutter codebase for someone coming from backend Python/Java.

---

## Project Structure — The Big Picture

```
mobile/penny/
├── lib/                    ← YOUR CODE (the only folder you regularly edit)
│   ├── main.dart           ← Entry point
│   ├── config/
│   │   └── app_config.dart ← Reads .env (like config.py / Settings)
│   ├── services/
│   │   ├── auth_service.dart      ← Wraps Supabase auth SDK
│   │   ├── api_service.dart       ← HTTP client for FastAPI backend
│   │   └── deep_link_service.dart ← Listens for pennyapp:// URLs
│   ├── models/
│   │   └── connection.dart        ← Data class (like a Pydantic schema)
│   ├── providers/
│   │   ├── auth_provider.dart         ← State management for auth
│   │   └── connections_provider.dart  ← State management for bank connections
│   └── screens/
│       ├── auth_gate.dart         ← Router: logged in → Home, logged out → Login
│       ├── home_screen.dart       ← Dashboard placeholder + bank summary
│       ├── connections_screen.dart ← Bank connections list + connect/disconnect
│       ├── login_screen.dart      ← Email/password sign-in
│       └── sign_up_screen.dart    ← Email/password registration
├── android/                ← Android-specific config (AndroidManifest.xml, Gradle)
├── ios/                    ← iOS-specific config (Info.plist, Xcode project)
├── web/                    ← Web entry point (index.html)
├── linux/                  ← Linux desktop config
├── macos/                  ← macOS desktop config
├── windows/                ← Windows desktop config
├── test/                   ← Test files
├── pubspec.yaml            ← Dependencies (like requirements.txt / pom.xml)
├── pubspec.lock            ← Pinned versions (like pip freeze output)
├── analysis_options.yaml   ← Static analysis rules (like pylint/flake8 config)
└── .env                    ← Environment variables (same concept as backend .env)
```

### `lib/` vs platform folders

`lib/` is where all Dart application logic lives. It compiles to every platform. Equivalent to `src/` in Java or `app/` in FastAPI.

The platform folders (`android/`, `ios/`, `web/`, etc.) are **not generated from `lib/`**. They were created once by `flutter create` and are persistent. Flutter's build system compiles your Dart code in `lib/` and packages it into each platform's native wrapper. You only touch these for platform-specific config — like adding the `pennyapp://` deep link scheme to `AndroidManifest.xml` and `Info.plist`.

**Analogy:** `lib/` is your Java source code. The platform folders are like the Dockerfile, `build.gradle`, or Xcode project — build/deployment config that wraps your actual code.

---

## Dependency Graph

```
main.dart                              ← Entry point
  ├── config/app_config.dart           ← Reads .env
  ├── services/deep_link_service.dart  ← Listens for incoming pennyapp:// URLs
  ├── providers/connections_provider.dart
  │     └── services/api_service.dart  ← HTTP client for backend
  │           └── config/app_config.dart
  └── screens/auth_gate.dart           ← Router
        ├── screens/home_screen.dart
        │     ├── providers/connections_provider.dart
        │     └── screens/connections_screen.dart
        │           ├── providers/connections_provider.dart
        │           └── services/api_service.dart (via provider)
        ├── screens/login_screen.dart
        │     └── providers/auth_provider.dart
        │           └── services/auth_service.dart
        └── screens/sign_up_screen.dart
              └── providers/auth_provider.dart
```

---

## File-by-File Walkthrough

### `main.dart` — Entry point

**Backend equivalent:** Python's `if __name__ == "__main__"` or Java's `public static void main()`.

**Key concepts:**

- **`main()` function** — The entry point. `async`/`await` works identically to Python. Three sequential setup calls: load .env, init Supabase, init deep links. Then `runApp()` starts the UI.

- **Widgets** — The big mental shift from backend. In Flutter, *everything on screen is a widget*. A widget is a class with a `build()` method that returns other widgets. Think of it as a function that returns HTML, except it returns a tree of Dart objects. They nest like Russian dolls:

```
ProviderScope           ← Riverpod dependency injection container
  └── PennyApp          ← Configures theme, app name
      └── MaterialApp   ← Provides navigation, theming, scaffold
          └── _DeepLinkHandler   ← Invisible, listens for deep links
              └── AuthGate       ← Decides: show login or home?
```

- **`StatelessWidget` vs `StatefulWidget`** — `PennyApp` extends `StatelessWidget`: no mutable internal state, its `build()` is a pure function of its inputs. `_DeepLinkHandler` extends `ConsumerStatefulWidget` because it needs lifecycle methods (`initState`, `dispose`) — like a Java class implementing `Closeable` where you set up and tear down resources.

- **`ConsumerWidget` / `ConsumerStatefulWidget`** — Riverpod's versions. The `Consumer` prefix means "this widget can access Riverpod providers". The `ref` parameter in `build(context, ref)` is the dependency injection handle — like `Depends()` in FastAPI.

- **`ProviderScope`** — Riverpod's dependency injection container. Equivalent to Spring's `ApplicationContext` or FastAPI's dependency injection system. Every provider lives here. Wrapping the entire app means every widget below can access any provider.

- **`_DeepLinkHandler`** — The underscore prefix `_` makes it file-private in Dart (like Python's convention, but enforced by the compiler). This widget does nothing visible (`build()` just returns `widget.child`). It exists solely to wire the deep link service to the connections provider. When a `pennyapp://callback?code=...` URL arrives, `_handleCallback` sends the code to the backend and shows a toast (SnackBar).

---

### `config/app_config.dart` — Environment config

**Backend equivalent:** `backend/app/config.py` with pydantic `Settings`.

Same idea: read env vars, fail fast if missing. `static` means class-level methods (like `@staticmethod` in Python). `get` is a Dart getter — calling `AppConfig.supabaseUrl` looks like reading a field but actually executes a function. Similar to a Python `@property`.

---

### `services/auth_service.dart` — Supabase auth wrapper

**Backend equivalent:** Repository/DAO pattern in Java — wraps the Supabase SDK with a clean interface.

**Key Dart concepts:**

- **Constructor `AuthService(this._client)`** — Dart shorthand for "accept a parameter and assign it to the `_client` field". Equivalent to Java constructor injection.

- **`Stream<AuthState>`** — Like a Python `AsyncGenerator` or Java `Observable`/`Flux`. Emits values over time. When the user signs in, signs out, or the token refreshes, a new `AuthState` event is emitted. Widgets subscribe to this to reactively update the UI.

- **`Future<T>`** — Dart's equivalent of Python's `Coroutine` / Java's `CompletableFuture`. The `async`/`await` syntax works identically to Python.

---

### `services/api_service.dart` — HTTP client for the FastAPI backend

**Backend equivalent:** A typed Python `httpx` client class or Java `RestTemplate`/`WebClient` wrapper.

**Key patterns:**

- **`_authHeaders()`** grabs the JWT from Supabase's session and attaches it as a Bearer token. This is the same JWT that the backend's `get_current_user` dependency verifies via JWKS. The Supabase SDK handles token refresh automatically, so the token is always valid when we read it.

- **`_handleResponse()`** is a centralised response handler. If the backend returns `{"detail": "..."}` (standard FastAPI error format), it extracts the message. Otherwise throws a generic `ApiException`. Same pattern as Java's `ResponseErrorHandler`.

- **Constructor `ApiService({http.Client? client})`** — The `?` means optional. In tests you inject a mock HTTP client; in production it uses the default. Same idea as Java constructor injection with a default.

- **Each method maps 1:1 to a backend endpoint.** `initiateConnection()` returns a `String` (the auth URL), `listConnections()` returns `List<Map<String, dynamic>>` (raw JSON maps, later converted to `BankConnection` objects in the provider).

---

### `services/deep_link_service.dart` — Incoming URL handler

Handles the mobile OS telling our app "someone opened a `pennyapp://...` URL".

- **Cold start** — App wasn't running. OS launched it via the deep link. `getInitialLink()` returns that URL.
- **Warm start** — App was already running in the background. `uriLinkStream` emits URLs as they arrive.

The `onCallbackReceived` field is a function reference — like a Python callback or Java `Consumer<String>`. Set by `_DeepLinkHandler` in `main.dart`. When a URI arrives, `_handleUri` validates it's `pennyapp://callback`, extracts the `code` query parameter, and calls the callback.

`debugPrint` — like Python's `logging.debug()`. Only shows in development.

---

### `models/connection.dart` — Data class

**Backend equivalent:** Mirrors `ConnectionOut` from `backend/app/models/schemas.py` (Pydantic `BaseModel`).

**Key Dart concepts:**

- All fields are `final` (immutable) — like a Python `frozen=True` dataclass or Java `record`.
- `required` in the constructor means the field must be provided. Fields without `required` (like `this.lastSyncedAt`) are optional and default to `null`.
- **`factory BankConnection.fromJson()`** — A named constructor that parses JSON. Dart equivalent of Pydantic's `model_validate()` or Jackson's `@JsonCreator`. Dart doesn't have automatic JSON deserialization, so you write the mapping by hand (or use code generation).
- **`String?`** — The `?` means nullable. Same as Python's `Optional[str]` or Java's `@Nullable`.

---

### `providers/auth_provider.dart` — Auth state management

**Backend equivalent:** Singleton service beans in a Spring container, but reactive.

**Key concepts:**

- **`Provider<AuthService>`** — Creates a single `AuthService` instance. Like `@Bean` in Spring or a FastAPI `Depends()` that returns a singleton. Any widget calls `ref.read(authServiceProvider)` to get this instance.

- **`StreamProvider<AuthState>`** — Wraps the auth state stream. When a widget calls `ref.watch(authStateProvider)`, it gets an `AsyncValue<AuthState>` that automatically updates when the stream emits. The widget *rebuilds itself* when the value changes. Declarative model: instead of "when auth changes, call this method to update the UI", you say "my UI is a function of the auth state".

- **`ref.watch()` vs `ref.read()`** — Critical distinction:
  - `ref.watch(provider)` — Subscribe. Rebuild this widget whenever the value changes. Used in `build()` methods.
  - `ref.read(provider)` — One-shot read. Get the current value without subscribing. Used in event handlers (button press, etc).

---

### `providers/connections_provider.dart` — Bank connections state

The most architecturally interesting file. `ConnectionsNotifier` is a **service layer + state container** combined.

**Key concepts:**

- **`AsyncNotifier<List<BankConnection>>`** — A Riverpod class that holds async state. The type parameter is the data it manages. Like a Spring `@Service` that also holds a cache of its data.

- **`build()` method** — Called automatically the first time anyone `ref.watch(connectionsProvider)`. Fetches from the backend and returns the initial state. Lazy-loaded singleton.

- **`state`** — Internal state variable, type `AsyncValue<List<BankConnection>>`. A sealed union with three variants:
  - `AsyncValue.data(connections)` — success
  - `AsyncValue.loading()` — request in flight
  - `AsyncValue.error(e, stackTrace)` — failure

- **Optimistic deletion** — When the user deletes a connection, immediately remove from local state (instant UI feedback), then send the DELETE request. If it fails, refetch the full list to roll back. Common UX pattern.

- **`AsyncValue.guard()`** — Convenience wrapper: runs an async function and catches exceptions, returning either `AsyncValue.data(result)` or `AsyncValue.error(e, stack)`. Like a try/catch that wraps the result in a union type.

---

### `screens/auth_gate.dart` — The router

**Backend equivalent:** Middleware that checks authentication before routing to the correct handler.

`ref.watch(_authStreamProvider)` subscribes to the auth state stream. Every time an auth event fires, `build()` re-executes. The `.when()` pattern is pattern matching on the `AsyncValue`:

```
Has data?
  ├── Session exists? → HomeScreen
  └── No session?     → LoginScreen
Loading? → Show spinner
Error?   → Show LoginScreen (let user retry)
```

No imperative navigation code. The widget tree *declaratively swaps* which screen is rendered based on state. Fundamental difference from backend routing — reactive, not imperative.

---

### `screens/home_screen.dart` — Dashboard placeholder

**Key patterns for a backend developer:**

- **Widget tree as UI** — The `build()` method is a single `return` statement describing the entire screen as a nested widget tree. Like JSX in React or Thymeleaf templates, but pure Dart. Each nesting level is a layout instruction:

```
Scaffold              ← App chrome (app bar, body area)
  └── Column          ← Vertical stack (like CSS flex-direction: column)
      ├── Card        ← Material design card (elevated surface)
      ├── Card        ← Banks summary (tappable)
      └── Expanded    ← Fill remaining space
```

- **`Navigator.of(context).push()`** — Imperative navigation. Pushing a `MaterialPageRoute` adds a new screen to the navigation stack with a back button — like navigating between pages in a web app.

- **`ref.watch(connectionsProvider)`** — Reactive connection to the provider. When the connections list changes (loaded, added, deleted), this widget automatically rebuilds. `.when()` handles all three states (data/loading/error).

- **`_BanksSummaryCard`** — A private sub-widget, extracted to keep the main `build()` readable. Like extracting a private method in Java. Takes data as constructor parameters (dependency injection at the widget level).

---

### `screens/connections_screen.dart` — Bank connections list

The largest screen file. Contains the main screen plus three private sub-widgets.

**Key patterns:**

- **`_connectBank()`** — The connect flow handler. Imperative code inside a button press: call backend, get URL, launch browser. `launchUrl()` opens the system browser. `context.mounted` is a safety check — since the function is async, the widget might have been removed from the screen by the time the `await` finishes. Same concept as checking if a request is still valid after an async operation.

- **`showDialog<bool>()`** — Returns a `Future<bool?>`. The dialog pops a value when the user taps a button (`Navigator.of(context).pop(true)`). The `await` resumes with that value. Like a synchronous user prompt that suspends the coroutine.

- **`ListView.builder`** — Virtual/lazy list. Calls `itemBuilder` only for items visible on screen, not all items upfront. Same concept as pagination — only render what you need.

- **`SnackBar`** — Toast notification at the bottom of the screen. `ScaffoldMessenger.of(context)` finds the nearest Scaffold and shows it. Like a flash message in a web framework.

---

## The Full Connect-Bank Flow

```
 1. User taps "Connect Bank" (FAB on ConnectionsScreen)
 2. ConnectionsScreen._connectBank()
 3.   → ref.read(connectionsProvider.notifier).initiateConnection()
 4.     → ApiService.initiateConnection()
 5.       → POST /api/v1/connections/initiate
          Headers: { Authorization: Bearer <supabase_jwt> }
 6.     ← FastAPI verifies JWT, calls TrueLayer, returns { "auth_url": "..." }
 7. launchUrl(authUrl) → system browser opens TrueLayer
 8. User authorises at their bank in TrueLayer sandbox
 9. TrueLayer redirects to pennyapp://callback?code=abc123
10. OS delivers deep link to the app
11. DeepLinkService._handleUri() → extracts code="abc123"
12. DeepLinkService.onCallbackReceived("abc123")
13. _DeepLinkHandler._handleCallback("abc123")
14.   → ref.read(connectionsProvider.notifier).completeCallback("abc123")
15.     → ApiService.connectionCallback("abc123")
16.       → POST /api/v1/connections/callback { "code": "abc123" }
17.     ← FastAPI exchanges code for tokens, stores connection
18.     → _fetchConnections() → GET /api/v1/connections/
19.   state = AsyncValue.data([...updated connections])
20. All widgets watching connectionsProvider rebuild automatically
21. SnackBar: "Bank connected successfully!"
```

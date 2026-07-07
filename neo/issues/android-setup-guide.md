# Android SDK & NDK Setup Guide (Garuda / Arch Linux)

This guide documents how to install the bare-minimum Android build tools (SDK, NDK, JDK) using `yay` and how to export the correct environment variables for **Zsh**, **Bash**, and **Fish** shells.

---

## 1. Installation via `yay` (Pacman + AUR)

Run the following command to install the required packages:

```bash
yay -Sy android-sdk-cmdline-tools-latest jdk17-openjdk android-ndk
```

*   `jdk17-openjdk`: The Java Development Kit required by the Android build tools.
*   `android-sdk-cmdline-tools-latest`: Installs the CLI manager (`sdkmanager`) to handle Android platforms.
*   `android-ndk`: Installs the Android C/C++ cross-compiler tools.

### ⚠️ Important: Fix Directory Permissions
By default, the AUR package installs the SDK into `/opt/android-sdk` with `root` ownership. This will cause `sdkmanager` updates to fail with permission warnings. 

To fix this, change the folder ownership to your user account (replace `vista` with your username if different):

```bash
sudo chown -R vista:vista /opt/android-sdk
```

---

## 2. Environment Variable Exports (By Shell)

After installation, the tools are located in:
*   **Android SDK Root:** `/opt/android-sdk`
*   **Android NDK Root:** `/opt/android-ndk`
*   **Java JDK 17:** `/usr/lib/jvm/java-17-openjdk`

Configure your preferred shell using the instructions below:

### 🔹 Zsh (`~/.zshrc`)
Append the following lines to your `~/.zshrc`:

```bash
# Android SDK & NDK Environment Configuration
export ANDROID_HOME="/opt/android-sdk"
export ANDROID_NDK_HOME="/opt/android-ndk"
export JAVA_HOME="/usr/lib/jvm/java-17-openjdk"
export PATH="$PATH:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools"
```
Reload your configuration:
```bash
source ~/.zshrc
```

---

### 🔹 Bash (`~/.bashrc`)
Append the following lines to your `~/.bashrc`:

```bash
# Android SDK & NDK Environment Configuration
export ANDROID_HOME="/opt/android-sdk"
export ANDROID_NDK_HOME="/opt/android-ndk"
export JAVA_HOME="/usr/lib/jvm/java-17-openjdk"
export PATH="$PATH:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools"
```
Reload your configuration:
```bash
source ~/.bashrc
```

---

### 🔹 Fish (`~/.config/fish/config.fish`)
Append the following lines to your `~/.config/fish/config.fish` (create the file if it does not exist):

```fish
# Android SDK & NDK Environment Configuration
set -gx ANDROID_HOME /opt/android-sdk
set -gx ANDROID_NDK_HOME /opt/android-ndk
set -gx JAVA_HOME /usr/lib/jvm/java-17-openjdk

# Add tools to PATH cleanly
fish_add_path $ANDROID_HOME/cmdline-tools/latest/bin
fish_add_path $ANDROID_HOME/platform-tools
```
Reload your configuration:
```fish
source ~/.config/fish/config.fish
```

---

## 3. Post-Installation Verification

To ensure everything was installed and mapped correctly:

1.  **Accept Android SDK Licenses** (Crucial: Gradle builds will fail otherwise):
    ```bash
    sdkmanager --licenses
    ```
    Press `y` and hit `Enter` to accept all prompt licenses.

2.  **Verify tools are visible**:
    ```bash
    sdkmanager --version
    adb --version
    java -version
    ```

3.  **Install SDK target platforms** (Recommended standard for API Level 34):
    ```bash
    sdkmanager "platforms;android-34" "build-tools;34.0.0"
    ```

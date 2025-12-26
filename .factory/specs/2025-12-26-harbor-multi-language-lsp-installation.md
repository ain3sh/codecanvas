
## Harbor Multi-Language LSP Installation Spec

### Current State
Only `basedpyright-langserver` (Python) is installed. CodeCanvas supports 8 language servers but 7 are missing.

### LSP Installation Analysis

| LSP | Binary | Method | Size | Complexity |
|-----|--------|--------|------|------------|
| **clangd** | `clangd` | apt-get | ~50MB | Trivial |
| **typescript-language-server** | `typescript-language-server` | npm -g | ~20MB | Trivial |
| **bash-language-server** | `bash-language-server` | npm -g | ~5MB | Trivial |
| **rust-analyzer** | `rust-analyzer` | wget prebuilt | ~40MB | Easy |
| **gopls** | `gopls` | go install | ~35MB (+500MB Go) | Medium |
| **solargraph** | `solargraph` | gem install | ~30MB (+50MB Ruby) | Medium |
| **jdtls** | `jdtls` | tar.gz + wrapper | ~50MB (+200MB JDK) | Hard |

---

### Proposed Changes to `install-claude-code-mcp.sh.j2`

#### 1. Add apt dependencies (clangd)
```bash
apt-get install -y curl git build-essential libcairo2-dev clangd
```

#### 2. Add npm LSPs after Node.js installation
```bash
echo "=== Installing Language Servers (npm) ==="
npm install -g typescript-language-server typescript bash-language-server
```

#### 3. Add rust-analyzer (prebuilt binary)
```bash
echo "=== Installing rust-analyzer ==="
curl -L https://github.com/rust-lang/rust-analyzer/releases/latest/download/rust-analyzer-x86_64-unknown-linux-gnu.gz | gunzip > /usr/local/bin/rust-analyzer
chmod +x /usr/local/bin/rust-analyzer
```

#### 4. Add Go + gopls (optional, heavy)
```bash
echo "=== Installing Go and gopls ==="
curl -L https://go.dev/dl/go1.23.4.linux-amd64.tar.gz | tar -C /usr/local -xzf -
export PATH="/usr/local/go/bin:$HOME/go/bin:$PATH"
go install golang.org/x/tools/gopls@latest
echo 'export PATH="/usr/local/go/bin:$HOME/go/bin:$PATH"' >> /etc/profile.d/go-path.sh
```

#### 5. Add Ruby + solargraph (optional, medium)
```bash
echo "=== Installing Ruby and solargraph ==="
apt-get install -y ruby ruby-dev
gem install solargraph --no-document
```

#### 6. Add JDK + jdtls (optional, complex)
```bash
echo "=== Installing JDK and jdtls ==="
apt-get install -y openjdk-21-jdk-headless python3
JDTLS_VERSION="1.54.0-202511200503"
curl -L "https://download.eclipse.org/jdtls/snapshots/jdt-language-server-${JDTLS_VERSION}.tar.gz" | tar -C /opt -xzf -
# Create wrapper script
cat > /usr/local/bin/jdtls << 'EOF'
#!/bin/bash
exec /usr/bin/java \
  -Declipse.application=org.eclipse.jdt.ls.core.id1 \
  -Dosgi.bundles.defaultStartLevel=4 \
  -Declipse.product=org.eclipse.jdt.ls.core.product \
  -Xmx1g \
  --add-modules=ALL-SYSTEM \
  --add-opens java.base/java.util=ALL-UNNAMED \
  --add-opens java.base/java.lang=ALL-UNNAMED \
  -jar /opt/plugins/org.eclipse.equinox.launcher_*.jar \
  -configuration /opt/config_linux \
  "$@"
EOF
chmod +x /usr/local/bin/jdtls
```

---

### Option A: Performance-Optimized (Recommended)
**Install:** clangd, typescript-language-server, bash-language-server, rust-analyzer  
**Skip:** gopls, solargraph, jdtls  
**Total size:** ~115MB additional  
**Coverage:** Python, C/C++, TypeScript/JavaScript, Rust, Shell (5/8 languages)

### Option B: Full Coverage (Maximum Compatibility)
**Install:** All 7 LSPs  
**Total size:** ~850MB additional  
**Coverage:** All 8 languages  
**Tradeoff:** Longer build, larger image, Go/Ruby/Java toolchain overhead

---

### Implementation Notes

1. **Layer ordering:** Group by package manager for Docker cache optimization
2. **PATH persistence:** Use `/etc/profile.d/*.sh` for login shells
3. **Parallel npm installs:** Single `npm install -g` command for all npm packages
4. **Prebuilt binaries:** rust-analyzer has official Linux x86_64 binaries
5. **gopls quirk:** No prebuilt binaries; requires Go toolchain
6. **jdtls quirk:** Needs wrapper script; launcher jar glob pattern required

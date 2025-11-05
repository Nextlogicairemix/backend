const API_BASE_URL = 'https://back-thbr.onrender.com';

const savedRole = localStorage.getItem("role");
const savedAccessCode = localStorage.getItem("accessCode");
const savedCourseCompleted = localStorage.getItem("courseCompleted") === "true";

// Apply role styling on page load
if (savedRole === "admin") {
    document.body.classList.add("admin-mode");
    console.log("👩‍🏫 Admin/Teacher mode active");
} else if (savedRole === "student") {
    document.body.classList.add("student-mode");
    console.log("🎓 Student mode active with access code:", savedAccessCode);
}

const toolThemes = {
    tweet: { bg: "from-blue-400 to-cyan-500", name: "Twitter" },
    linkedin: { bg: "from-blue-600 to-blue-800", name: "LinkedIn" },
    email: { bg: "from-orange-400 to-red-500", name: "Email" },
    blog: { bg: "from-purple-500 to-pink-600", name: "Blog" },
    summary: { bg: "from-green-400 to-emerald-600", name: "Summary" },
    default: { bg: "from-purple-600 to-pink-500", name: "Default" }
};

function setToolTheme(toolType) {
    const theme = toolThemes[toolType] || toolThemes.default;
    const body = document.getElementById("page-body");
    
    // Remove all tool theme classes
    Object.keys(toolThemes).forEach(key => {
        body.classList.remove(`tool-bg-${key}`);
    });
    
    // Add current theme
    body.className = `bg-gradient-to-br ${theme.bg} min-h-screen text-white font-sans transition-all duration-500`;
    
    // Store current tool for teacher visibility
    localStorage.setItem("currentTool", toolType);
    console.log(`🎨 Tool theme changed to: ${theme.name}`);
}

let userState = {
    isLoggedIn: false,
    role: savedRole || 'guest',
    courseCompleted: savedCourseCompleted || false,
    accessCode: savedAccessCode || null,
    isPremium: false,
    usesLeft: 3
};

async function checkSession() {
    try {
        const response = await fetch(`${API_BASE_URL}/check_session`, {
            method: 'GET',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' }
        });
        
        if (response.ok) {
            const data = await response.json();
            userState = {
                ...userState,
                isLoggedIn: data.logged_in || false,
                role: data.role || 'guest',
                courseCompleted: data.course_completed || false,
                isPremium: data.is_premium || false,
                usesLeft: data.uses_left || 3
            };
            
            // Sync to localStorage
            if (data.logged_in) {
                localStorage.setItem("role", data.role);
                localStorage.setItem("courseCompleted", data.course_completed);
            }
            
            updateUI();
        }
    } catch (error) {
        console.error('Session check failed:', error);
    }
}

async function login(username, password, accessCode = null) {
    try {
        const response = await fetch(`${API_BASE_URL}/login`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                username, 
                password,
                access_code: accessCode 
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            userState = {
                isLoggedIn: true,
                role: data.user.role,
                courseCompleted: data.user.course_completed,
                accessCode: accessCode,
                isPremium: false,
                usesLeft: 999 // Logged in = unlimited basic remixes
            };
            
            // Save to localStorage
            localStorage.setItem("role", data.user.role);
            localStorage.setItem("courseCompleted", data.user.course_completed);
            if (accessCode) localStorage.setItem("accessCode", accessCode);
            
            // Apply role styling
            document.body.classList.remove("admin-mode", "student-mode");
            document.body.classList.add(`${data.user.role}-mode`);
            
            // Redirect based on course completion
            if (!data.user.course_completed && data.user.role === 'student') {
                alert("Welcome! Please complete the course before accessing tools.");
                window.location.href = '/course.html';
            } else {
                alert(`Welcome ${data.user.role === 'admin' ? 'Teacher' : 'Student'}!`);
                updateUI();
            }
        } else {
            alert(data.error || 'Login failed');
        }
    } catch (error) {
        console.error('Login error:', error);
        alert('Connection error during login');
    }
}

function logout() {
    localStorage.removeItem("role");
    localStorage.removeItem("accessCode");
    localStorage.removeItem("courseCompleted");
    localStorage.removeItem("currentTool");
    
    document.body.classList.remove("admin-mode", "student-mode");
    
    userState = {
        isLoggedIn: false,
        role: 'guest',
        courseCompleted: false,
        accessCode: null,
        isPremium: false,
        usesLeft: 3
    };
    
    fetch(`${API_BASE_URL}/logout`, { 
        method: 'POST', 
        credentials: 'include' 
    });
    
    updateUI();
    alert('Logged out successfully');
}

function updateUI() {
    const loginBtn = document.getElementById('login-btn');
    const logoutBtn = document.getElementById('logout-btn');
    const upgradeBtn = document.getElementById('upgrade-btn');
    const generateBtn = document.getElementById('generate-btn');
    
    if (!userState.isLoggedIn) {
        // Guest mode
        loginBtn?.classList.remove('hidden');
        logoutBtn?.classList.add('hidden');
        upgradeBtn?.classList.remove('hidden');
        if (generateBtn) generateBtn.textContent = `Generate (${userState.usesLeft} left)`;
    } else if (userState.role === 'admin') {
        // Teacher/Admin mode
        loginBtn?.classList.add('hidden');
        logoutBtn?.classList.remove('hidden');
        upgradeBtn?.classList.add('hidden');
        if (generateBtn) generateBtn.textContent = 'Generate';
        
        // Show admin dashboard link
        showAdminDashboard();
    } else if (userState.role === 'student') {
        // Student mode
        loginBtn?.classList.add('hidden');
        logoutBtn?.classList.remove('hidden');
        
        if (!userState.courseCompleted) {
            // Block tools until course complete
            if (generateBtn) {
                generateBtn.disabled = true;
                generateBtn.textContent = '🔒 Complete Course First';
            }
        } else {
            if (userState.isPremium) {
                upgradeBtn?.classList.add('hidden');
                if (generateBtn) generateBtn.textContent = '✨ Generate (Premium)';
            } else {
                upgradeBtn?.classList.remove('hidden');
                if (generateBtn) generateBtn.textContent = 'Generate (Unlimited)';
            }
        }
    }
}

function showAdminDashboard() {
    // Add admin panel button if it doesn't exist
    const header = document.querySelector('header .flex.gap-3');
    if (header && !document.getElementById('admin-panel-btn')) {
        const btn = document.createElement('button');
        btn.id = 'admin-panel-btn';
        btn.className = 'bg-green-500 hover:bg-green-600 px-4 py-2 rounded-lg font-semibold';
        btn.textContent = '👩‍🏫 Admin Panel';
        btn.onclick = () => window.location.href = '/admin.html';
        header.appendChild(btn);
    }
}


document.getElementById('tool-select')?.addEventListener('change', (e) => {
    const selectedTool = e.target.value;
    setToolTheme(selectedTool);
});


document.getElementById('generate-btn')?.addEventListener('click', async () => {
    const inputText = document.getElementById('input-text')?.value.trim();
    const toolType = document.getElementById('tool-select')?.value;
    const outputDiv = document.getElementById('output-text');
    
    if (!inputText) {
        alert('Please enter some content first!');
        return;
    }
    
    // Check permissions
    if (!userState.isLoggedIn) {
        if (userState.usesLeft <= 0) {
            alert('Out of free uses! Please sign up.');
            return;
        }
    } else if (userState.role === 'student' && !userState.courseCompleted) {
        alert('Please complete the course before using tools!');
        window.location.href = '/course.html';
        return;
    }
    
    // Make API call
    try {
        outputDiv.textContent = '⏳ Generating...';
        
        const response = await fetch(`${API_BASE_URL}/remix`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                content: inputText,
                style: toolType,
                is_guest: !userState.isLoggedIn
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            outputDiv.textContent = data.output;
            document.getElementById('copy-btn')?.classList.remove('hidden');
            
            // Update uses for guests
            if (!userState.isLoggedIn) {
                userState.usesLeft--;
                updateUI();
            }
        } else {
            outputDiv.textContent = `❌ Error: ${data.error}`;
        }
    } catch (error) {
        console.error('Generation error:', error);
        outputDiv.textContent = '❌ Connection error';
    }
});

document.getElementById('copy-btn')?.addEventListener('click', async () => {
    const text = document.getElementById('output-text')?.textContent;
    try {
        await navigator.clipboard.writeText(text);
        alert('✅ Copied to clipboard!');
    } catch (err) {
        alert('Failed to copy');
    }
});

window.addEventListener('DOMContentLoaded', () => {
    console.log('🚀 Educational Platform Initialized');
    console.log(`📊 User State:`, userState);
    
    checkSession();
    updateUI();
    
    // Set initial theme from localStorage if available
    const lastTool = localStorage.getItem('currentTool');
    if (lastTool) setToolTheme(lastTool);
});
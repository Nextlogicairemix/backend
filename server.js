// server.js - Complete NextLogic AI Backend
const express = require('express');
const cors = require('cors');
const cookieParser = require('cookie-parser');
const bcrypt = require('bcryptjs');
const jwt = require('jsonwebtoken');
const axios = require('axios');

const app = express();
const PORT = process.env.PORT || 5000;
const JWT_SECRET = process.env.JWT_SECRET || 'nextlogic-secret-key-change-in-production';
const GEMINI_API_KEY = process.env.GEMINI_API_KEY;

// In-memory storage
const users = [];
const aiUsageLog = [];
const assignments = [
  {
    id: '1',
    name: 'Essay: American History',
    deadline: 'Tomorrow',
    aiAllowed: true,
    description: 'Write a 500-word essay on the American Revolution'
  },
  {
    id: '2',
    name: 'Math Problem Set',
    deadline: '2 days',
    aiAllowed: false,
    description: 'Complete problems 1-20 from Chapter 5'
  },
  {
    id: '3',
    name: 'Science Lab Report',
    deadline: '1 week',
    aiAllowed: true,
    description: 'Document your chemistry experiment findings'
  }
];

// Middleware
app.use(express.json());
app.use(cookieParser());
app.use(cors({
  origin: [
    'http://localhost:3000',
    'https://nlogic.netlify.app',
    'https://www.nextlogicai.com',
    'https://nextlogicai.com',
    process.env.FRONTEND_URL
  ].filter(Boolean),
  credentials: true
}));

// Helper: Generate JWT Token
const generateToken = (userId) => {
  return jwt.sign({ userId }, JWT_SECRET, { expiresIn: '7d' });
};

// Helper: Verify JWT Token
const verifyToken = (token) => {
  try {
    return jwt.verify(token, JWT_SECRET);
  } catch (error) {
    return null;
  }
};

// Middleware: Require Authentication
const requireAuth = (req, res, next) => {
  const token = req.cookies.token;
  if (!token) {
    return res.status(401).json({ error: 'Not authenticated' });
  }

  const decoded = verifyToken(token);
  if (!decoded) {
    return res.status(401).json({ error: 'Invalid token' });
  }

  const user = users.find(u => u.id === decoded.userId);
  if (!user) {
    return res.status(401).json({ error: 'User not found' });
  }

  req.user = user;
  next();
};

// Middleware: Require Teacher Role
const requireTeacher = (req, res, next) => {
  if (req.user.role !== 'admin') {
    return res.status(403).json({ error: 'Teacher access required' });
  }
  next();
};

// ============================================
// ROOT & HEALTH CHECK
// ============================================

app.get('/', (req, res) => {
  res.json({
    message: 'NextLogic AI Backend - Full System',
    version: '2.0.0',
    status: 'running',
    features: ['Auth', 'AI Remix', 'Teacher Monitoring', 'Assignments'],
    endpoints: {
      auth: ['/api/auth/register', '/api/auth/login', '/api/auth/logout', '/api/auth/me'],
      student: ['/api/student/assignments', '/api/ai/remix'],
      teacher: ['/api/teacher/activity', '/api/teacher/students', '/api/teacher/assignments']
    }
  });
});

// ============================================
// AUTH ROUTES
// ============================================

app.post('/api/auth/register', async (req, res) => {
  try {
    const { name, email, password, access_code } = req.body;

    if (!name || !email || !password) {
      return res.status(400).json({ error: 'Name, email, and password are required' });
    }

    if (password.length < 6) {
      return res.status(400).json({ error: 'Password must be at least 6 characters' });
    }

    const existingUser = users.find(u => u.email === email);
    if (existingUser) {
      return res.status(400).json({ error: 'Email already registered' });
    }

    const hashedPassword = await bcrypt.hash(password, 10);

    let role = 'student';
    if (access_code && access_code.toUpperCase().startsWith('TEACHER')) {
      role = 'admin';
    }

    const newUser = {
      id: Date.now().toString(),
      name,
      email,
      password: hashedPassword,
      role,
      aiUsageCount: 0,
      totalAIRequests: 0,
      createdAt: new Date().toISOString(),
      lastActive: new Date().toISOString()
    };

    users.push(newUser);
    console.log(`✅ New user registered: ${email} (${role})`);

    res.status(201).json({
      success: true,
      message: 'Registration successful! Please login.'
    });
  } catch (error) {
    console.error('❌ Register error:', error);
    res.status(500).json({ error: 'Registration failed' });
  }
});

app.post('/api/auth/login', async (req, res) => {
  try {
    const { email, password } = req.body;

    if (!email || !password) {
      return res.status(400).json({ error: 'Email and password are required' });
    }

    const user = users.find(u => u.email === email);
    if (!user) {
      return res.status(401).json({ error: 'Invalid email or password' });
    }

    const isValidPassword = await bcrypt.compare(password, user.password);
    if (!isValidPassword) {
      return res.status(401).json({ error: 'Invalid email or password' });
    }

    user.lastActive = new Date().toISOString();
    const token = generateToken(user.id);

    res.cookie('token', token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: process.env.NODE_ENV === 'production' ? 'none' : 'lax',
      maxAge: 7 * 24 * 60 * 60 * 1000
    });

    const { password: _, ...userWithoutPassword } = user;
    console.log(`✅ User logged in: ${email}`);

    res.json({
      success: true,
      user: userWithoutPassword
    });
  } catch (error) {
    console.error('❌ Login error:', error);
    res.status(500).json({ error: 'Login failed' });
  }
});

app.get('/api/auth/me', requireAuth, (req, res) => {
  const { password: _, ...userWithoutPassword } = req.user;
  res.json(userWithoutPassword);
});

app.post('/api/auth/logout', (req, res) => {
  res.clearCookie('token');
  console.log('✅ User logged out');
  res.json({ message: 'Logged out successfully' });
});

// ============================================
// STUDENT ROUTES
// ============================================

// Get student's assignments
app.get('/api/student/assignments', requireAuth, (req, res) => {
  if (req.user.role === 'admin') {
    return res.json({ assignments: [] }); // Teachers don't have assignments
  }

  const assignmentsWithStatus = assignments.map(a => ({
    ...a,
    status: Math.random() > 0.5 ? 'In Progress' : 'Not Started' // Mock status
  }));

  res.json({
    assignments: assignmentsWithStatus,
    totalAssignments: assignments.length
  });
});

// AI Remix endpoint
app.post('/api/ai/remix', requireAuth, async (req, res) => {
  try {
    const { content, remixType, assignmentId } = req.body;

    if (!content || !content.trim()) {
      return res.status(400).json({ error: 'Content is required' });
    }

    if (!GEMINI_API_KEY) {
      return res.status(500).json({ error: 'AI service not configured' });
    }

    // Check if assignment restricts AI (if assignmentId provided)
    if (assignmentId) {
      const assignment = assignments.find(a => a.id === assignmentId);
      if (assignment && !assignment.aiAllowed) {
        return res.status(403).json({ 
          error: 'AI is not allowed for this assignment',
          blocked: true
        });
      }
    }

    // Define remix prompts
    const remixPrompts = {
      tweet: 'Convert this into an engaging Twitter thread with 3-5 tweets. Use emojis and make it conversational.',
      linkedin: 'Rewrite this as a professional LinkedIn post with a hook, valuable insights, and a call-to-action.',
      instagram: 'Transform this into an Instagram caption with emojis, hashtags, and an engaging hook.',
      facebook: 'Rewrite this as a Facebook post that encourages engagement and comments.',
      reddit: 'Convert this into a Reddit post with a catchy title and detailed explanation.',
      youtube: 'Create a YouTube video description with timestamps, keywords, and SEO optimization.',
      tiktok: 'Write a short, catchy TikTok caption with trending hashtags.',
      pinterest: 'Create a Pinterest description that drives clicks with keywords and benefits.',
      summary: 'Summarize this content in 2-3 concise sentences.',
      bullets: 'Convert this into clear bullet points highlighting the key information.',
      expand: 'Expand this content with more details, examples, and explanations.',
      email: 'Write a professional email based on this content with a clear subject line.',
      ad: 'Create compelling ad copy with a strong headline and call-to-action.',
      blog: 'Expand this into a full blog post with introduction, body paragraphs, and conclusion.',
      story: 'Rewrite this as an engaging narrative story.',
      professional: 'Rewrite this in a professional, formal tone.',
      casual: 'Rewrite this in a casual, friendly tone.',
      creative: 'Rewrite this with creative flair and engaging language.'
    };

    const prompt = remixPrompts[remixType] || remixPrompts.professional;

    // Call Gemini API
    const response = await axios.post(
      `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${GEMINI_API_KEY}`,
      {
        contents: [{
          parts: [{
            text: `${prompt}\n\nContent to transform:\n${content}`
          }]
        }],
        generationConfig: {
          temperature: 0.7,
          maxOutputTokens: 2000
        }
      },
      {
        headers: { 'Content-Type': 'application/json' },
        timeout: 120000
      }
    );

    if (response.data && response.data.candidates && response.data.candidates.length > 0) {
      const remixedContent = response.data.candidates[0].content.parts[0].text;

      // Log AI usage
      const usageLog = {
        id: Date.now().toString(),
        userId: req.user.id,
        userName: req.user.name,
        userEmail: req.user.email,
        remixType,
        assignmentId: assignmentId || null,
        originalContent: content.substring(0, 100) + '...',
        contentLength: content.length,
        timestamp: new Date().toISOString(),
        timeAgo: 'Just now'
      };
      aiUsageLog.unshift(usageLog); // Add to beginning

      // Keep only last 100 logs
      if (aiUsageLog.length > 100) {
        aiUsageLog.pop();
      }

      // Update user stats
      req.user.aiUsageCount = (req.user.aiUsageCount || 0) + 1;
      req.user.totalAIRequests = (req.user.totalAIRequests || 0) + 1;
      req.user.lastActive = new Date().toISOString();

      console.log(`✅ AI Remix by ${req.user.name}: ${remixType}`);

      res.json({
        success: true,
        output: remixedContent,
        usageCount: req.user.aiUsageCount
      });
    } else {
      res.status(500).json({ error: 'No response from AI' });
    }
  } catch (error) {
    console.error('❌ AI Remix error:', error.response?.data || error.message);
    if (error.code === 'ECONNABORTED') {
      res.status(504).json({ error: 'AI request timed out. Please try with shorter content.' });
    } else {
      res.status(500).json({ error: 'Failed to process AI request' });
    }
  }
});

// ============================================
// TEACHER ROUTES
// ============================================

// Get real-time activity dashboard
app.get('/api/teacher/activity', requireAuth, requireTeacher, (req, res) => {
  // Get recent AI usage logs
  const recentLogs = aiUsageLog.slice(0, 20);
  
  // Get student stats
  const students = users
    .filter(u => u.role === 'student')
    .map(u => {
      const userLogs = aiUsageLog.filter(log => log.userId === u.id);
      const recentActivity = userLogs[0];
      
      return {
        id: u.id,
        name: u.name,
        email: u.email,
        aiUsageCount: u.aiUsageCount || 0,
        totalRequests: u.totalAIRequests || 0,
        lastActive: u.lastActive || 'Never',
        isActive: recentActivity && (Date.now() - new Date(recentActivity.timestamp) < 300000), // Active in last 5 min
        recentActivity: recentActivity ? `${recentActivity.remixType} - ${recentActivity.timeAgo}` : 'No activity'
      };
    });

  // Calculate stats
  const activeNow = students.filter(s => s.isActive).length;
  const totalUsage = aiUsageLog.length;
  const averageUsage = students.length > 0 ? (totalUsage / students.length).toFixed(1) : 0;

  res.json({
    success: true,
    stats: {
      totalStudents: students.length,
      activeNow,
      totalUsage,
      averageUsage,
      alertsToday: Math.floor(Math.random() * 5) // Mock alerts
    },
    recentActivity: recentLogs,
    students,
    timestamp: new Date().toISOString()
  });
});

// Get all students
app.get('/api/teacher/students', requireAuth, requireTeacher, (req, res) => {
  const students = users
    .filter(u => u.role === 'student')
    .map(({ password, ...student }) => ({
      ...student,
      aiUsageCount: student.aiUsageCount || 0
    }));

  res.json({
    success: true,
    students,
    count: students.length
  });
});

// Get/manage assignments
app.get('/api/teacher/assignments', requireAuth, requireTeacher, (req, res) => {
  res.json({
    success: true,
    assignments,
    count: assignments.length
  });
});

// ============================================
// TEST/DEBUG ENDPOINTS
// ============================================

app.get('/api/test/users', (req, res) => {
  const usersWithoutPasswords = users.map(({ password, ...user }) => user);
  res.json({
    count: users.length,
    users: usersWithoutPasswords
  });
});

app.get('/api/test/logs', (req, res) => {
  res.json({
    count: aiUsageLog.length,
    logs: aiUsageLog.slice(0, 10)
  });
});

// ============================================
// START SERVER
// ============================================

app.listen(PORT, () => {
  console.log('\n' + '='.repeat(70));
  console.log('🚀 NextLogic AI - Complete Backend System');
  console.log('='.repeat(70));
  console.log(`✅ Server running on http://localhost:${PORT}`);
  console.log(`🔒 Environment: ${process.env.NODE_ENV || 'development'}`);
  console.log(`🤖 Gemini API: ${GEMINI_API_KEY ? 'Configured ✓' : 'Missing ✗'}`);
  console.log('\n📚 Features:');
  console.log('   ✓ Student & Teacher Authentication');
  console.log('   ✓ AI Content Remix with Gemini');
  console.log('   ✓ Real-time Activity Monitoring');
  console.log('   ✓ Assignment Management');
  console.log('   ✓ AI Permission Controls');
  console.log('\n🎓 Access Codes:');
  console.log('   Student: No code needed (default)');
  console.log('   Teacher: TEACHER123 or any code starting with "TEACHER"');
  console.log('='.repeat(70) + '\n');
});
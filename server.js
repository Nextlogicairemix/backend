// server.js - NextLogic AI Backend with Gemini
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

// In-memory user storage (replace with database later)
const users = [];
const aiUsageLog = []; // Store AI usage for teacher monitoring

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

// ============================================
// AUTH ROUTES
// ============================================

app.get('/', (req, res) => {
  res.json({
    message: 'NextLogic AI API is running!',
    version: '2.0.0',
    endpoints: ['/api/auth/register', '/api/auth/login', '/api/auth/logout', '/api/auth/me', '/api/ai/remix']
  });
});

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
      createdAt: new Date().toISOString()
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
// AI REMIX ROUTES
// ============================================

app.post('/api/ai/remix', requireAuth, async (req, res) => {
  try {
    const { content, remixType } = req.body;

    if (!content || !content.trim()) {
      return res.status(400).json({ error: 'Content is required' });
    }

    if (!GEMINI_API_KEY) {
      return res.status(500).json({ error: 'AI service not configured' });
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
        userId: req.user.id,
        userName: req.user.name,
        remixType,
        originalContent: content.substring(0, 100) + '...',
        timestamp: new Date().toISOString()
      };
      aiUsageLog.push(usageLog);

      // Update user's AI usage count
      req.user.aiUsageCount = (req.user.aiUsageCount || 0) + 1;

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
// TEACHER MONITORING ROUTES
// ============================================

app.get('/api/teacher/activity', requireAuth, (req, res) => {
  if (req.user.role !== 'admin') {
    return res.status(403).json({ error: 'Teacher access required' });
  }

  // Get recent AI usage logs
  const recentLogs = aiUsageLog.slice(-20).reverse();
  
  // Get student stats
  const studentStats = users
    .filter(u => u.role === 'student')
    .map(u => ({
      id: u.id,
      name: u.name,
      email: u.email,
      aiUsageCount: u.aiUsageCount || 0,
      lastActive: aiUsageLog.find(log => log.userId === u.id)?.timestamp || 'Never'
    }));

  res.json({
    recentActivity: recentLogs,
    students: studentStats,
    totalUsage: aiUsageLog.length
  });
});

// ============================================
// TEST ENDPOINTS
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
    logs: aiUsageLog.slice(-10)
  });
});

// ============================================
// START SERVER
// ============================================

app.listen(PORT, () => {
  console.log('\n' + '='.repeat(60));
  console.log('🚀 NextLogic AI Backend Server with Gemini AI');
  console.log('='.repeat(60));
  console.log(`✅ Server running on http://localhost:${PORT}`);
  console.log(`🔒 Environment: ${process.env.NODE_ENV || 'development'}`);
  console.log(`🤖 Gemini API: ${GEMINI_API_KEY ? 'Configured ✓' : 'Missing ✗'}`);
  console.log('\n📚 Available endpoints:');
  console.log('   Auth:');
  console.log('   POST /api/auth/register');
  console.log('   POST /api/auth/login');
  console.log('   GET  /api/auth/me');
  console.log('   POST /api/auth/logout');
  console.log('\n   AI Features:');
  console.log('   POST /api/ai/remix');
  console.log('\n   Teacher:');
  console.log('   GET  /api/teacher/activity');
  console.log('\n💡 Tips:');
  console.log('   - Students can use AI remix tools');
  console.log('   - Teachers see all AI usage in real-time');
  console.log('   - Use TEACHER123 access code for admin role');
  console.log('='.repeat(60) + '\n');
});
import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './AuthContext';
import SEOWrapper from './components/SEOWrapper';
import AuthPage from './components/AuthPage';
import TeacherDashboard from './TeacherDashboard';
import StudentDashboard from './StudentDashboard';
import LandingPage from './pages/LandingPage';

const DashboardRoute = () => {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-900 via-purple-900 to-slate-900 flex items-center justify-center">
        <div className="text-center">
          <div className="w-16 h-16 border-4 border-purple-500/30 border-t-purple-500 rounded-full animate-spin mx-auto mb-4"></div>
          <p className="text-white/60 text-lg">Loading NextLogicAI...</p>
        </div>
      </div>
    );
  }

  // Not logged in - redirect to login
  if (!user) {
    return <Navigate to="/login" replace />;
  }

  // Show correct dashboard based on role
  if (user.role === 'admin') {
    return <TeacherDashboard />;
  }

  return <StudentDashboard />;
};

function App() {
  return (
    <AuthProvider>
      <Router>
        <Routes>
          {/* Public Landing Page */}
          <Route
            path="/"
            element={
              <SEOWrapper
                title="NextLogic AI - Stop AI Cheating Without Stopping AI"
                description="Give teachers real-time control over student AI usage. Monitor, prevent cheating, and teach responsible AI use. Trusted by 500+ schools."
                keywords="AI cheating prevention, teacher AI control, student AI monitoring, education technology"
                canonical="https://www.nextlogicai.com/"
              >
                <LandingPage />
              </SEOWrapper>
            }
          />

          {/* Login Page */}
          <Route
            path="/login"
            element={
              <SEOWrapper
                title="Login - NextLogic AI"
                description="Login to your NextLogic AI dashboard"
                noindex={true}
              >
                <AuthPage initialMode="login" />
              </SEOWrapper>
            }
          />

          {/* Signup Page */}
          <Route
            path="/signup"
            element={
              <SEOWrapper
                title="Start Free Trial - NextLogic AI"
                description="Start your 14-day free trial. No credit card required."
                noindex={false}
              >
                <AuthPage initialMode="signup" />
              </SEOWrapper>
            }
          />

          {/* Protected Dashboard Route */}
          <Route
            path="/dashboard"
            element={
              <SEOWrapper
                title="Dashboard - NextLogic AI"
                noindex={true}
              >
                <DashboardRoute />
              </SEOWrapper>
            }
          />

          {/* Redirect any unknown routes to landing page */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Router>
    </AuthProvider>
  );
}

export default App;

import React from 'react';
import { AuthProvider, useAuth } from './AuthContext';
import AuthPage from './AuthPage';
import TeacherDashboard from './TeacherDashboard';
import StudentDashboard from './StudentDashboard';

const AppContent = () => {
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

  // Not logged in - show auth page
  if (!user) {
    return <AuthPage />;
  }

  // Logged in as teacher/admin - show teacher dashboard
  if (user.role === 'admin') {
    return <TeacherDashboard />;
  }

  // Logged in as student - show student dashboard
  return <StudentDashboard />;
};

function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  );
}

export default App;
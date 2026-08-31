import { Navigate, Route, Routes } from 'react-router-dom';

import { AppLayout } from '@/features/app/AppLayout';
import { ForgotPasswordPage } from '@/features/auth/ForgotPasswordPage';
import { LoginPage } from '@/features/auth/LoginPage';
import { OnboardingPasskeyPage } from '@/features/auth/OnboardingPasskeyPage';
import { ResetPasswordPage } from '@/features/auth/ResetPasswordPage';
import { SignUpPage } from '@/features/auth/SignUpPage';
import { VerifyEmailPage } from '@/features/auth/VerifyEmailPage';
import { GuidePage } from '@/features/guide/GuidePage';
import { SearchPage } from '@/features/search/SearchPage';
import { SettingsPage } from '@/features/settings/SettingsPage';
import { SourceDetailPage } from '@/features/sources/SourceDetailPage';
import { SourcesPage } from '@/features/sources/SourcesPage';
import { RequireAuth } from '@/routes/RequireAuth';

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignUpPage />} />
      <Route path="/verify" element={<VerifyEmailPage />} />
      <Route path="/forgot" element={<ForgotPasswordPage />} />
      <Route path="/reset" element={<ResetPasswordPage />} />

      <Route
        path="/onboarding"
        element={
          <RequireAuth stage="onboarding">
            <OnboardingPasskeyPage />
          </RequireAuth>
        }
      />

      <Route
        path="/"
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        <Route index element={<GuidePage />} />
        <Route path="search" element={<SearchPage />} />
        <Route path="sources" element={<SourcesPage />} />
        <Route path="sources/:sourceId" element={<SourceDetailPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

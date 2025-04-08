// frontend/components/ErrorBoundary.js
// --- REVISION HISTORY ---
// 2025-04-07: Rev 2 - Migrated styles to CSS Module, integrated dark theme variables.
//           - Removed inline styles object.
//           - Created and imported ErrorBoundary.module.css.
//           - Applied CSS module classes to fallback UI elements.
//           - Styled fallback UI for dark theme using CSS variables.
//           - Strengthened TODO comment for error reporting service integration.
// 2025-04-07: Rev 1 - Initial implementation based on recommendation for _app.js.
//           - Catches JS errors during rendering in child components.
//           - Logs errors to console (should integrate with error reporting service).
//           - Displays a simple fallback UI.

import React from 'react';
import styles from './ErrorBoundary.module.css'; // Import CSS Module

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error) {
    // Update state to render fallback UI
    return { hasError: true, error: error };
  }

  componentDidCatch(error, errorInfo) {
    // Store errorInfo as well for potentially more detailed logging/display
    this.setState({ errorInfo: errorInfo });

    // Log the error and component stack trace
    console.error("ErrorBoundary caught an error:", error, errorInfo);

    // --- TODO: CRITICAL FOR PRODUCTION ---
    // Integrate with an error reporting service (e.g., Sentry, LogRocket, Datadog).
    // Replace console.error with service-specific logging.
    // Example: Sentry.captureException(error, { extra: errorInfo });
    // Example: logErrorToMyService(error, errorInfo.componentStack);
  }

  // Simple retry: reload the page.
  // More sophisticated retries might involve resetting specific context state,
  // but window reload is often the most reliable fallback for unexpected errors.
  handleRetry = () => {
    this.setState({ hasError: false, error: null, errorInfo: null }); // Reset state
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      // Fallback UI Rendering
      return (
        <div className={styles.fallbackContainer} role="alert">
          {/* Optional: Add an icon */}
          {/* <div className={styles.icon}>⚠️</div> */}
          <h2 className={styles.fallbackTitle}>Oops! Something Went Wrong</h2>
          <p className={styles.fallbackMessage}>
            An unexpected error occurred in the application. Please try refreshing the page.
            If the problem persists, please contact support or try again later.
          </p>

          {/* Display error details ONLY in development environment */}
          {process.env.NODE_ENV === 'development' && this.state.error && (
            <details className={styles.errorDetailsContainer}>
                <summary className={styles.errorDetailsSummary}>Error Details (Development Only)</summary>
                <pre className={styles.errorDetails}>
                    <strong>Error:</strong> {this.state.error.toString()}
                    {this.state.errorInfo?.componentStack && (
                        <>
                            <hr className={styles.hr} />
                            <strong>Component Stack:</strong>{this.state.errorInfo.componentStack}
                        </>
                    )}
                </pre>
            </details>
          )}

          {/* Use global button style */}
          <button onClick={this.handleRetry} className="button button-primary mt-3">
            Refresh Page
          </button>
        </div>
      );
    }

    // Render children normally if no error
    return this.props.children;
  }
}

export default ErrorBoundary;

// TODO: Create ErrorBoundary.module.css with styles for the fallback UI, using CSS variables for theme.
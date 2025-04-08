// frontend/context/AuthContext.js
// --- REVISION HISTORY ---
// 2025-04-07: Rev 2 - Added error toast for initial check failure, strengthened comments.
//           - Added showErrorToast call for non-401 errors during initial checkAuth.
//           - Strengthened comments about backend dependency for PGP status.
//           - Added comment about potential PGP status synchronization limitations mid-session.
//           - Refined cautionary comment for exposed setUser function.
// 2025-04-07: Rev 1 - Initial enterprise-grade review and update.
//           - CRITICAL FIX: Modified initial auth check (useEffect) to require and use a flag
//             from getCurrentUser response (e.g., `is_session_pgp_authenticated`) to correctly
//             set isPgpAuthenticated state on load/refresh. Emphasized backend requirement.
//           - Removed misleading comments suggesting localStorage for auth state. Emphasized HttpOnly cookie reliance.
//           - Confirmed logout clears state robustly in `finally` block.
//           - Removed console.log statements.
//           - Added explanatory comments.
//           - Added revision history block.

import React, { createContext, useState, useEffect, useContext, useCallback } from 'react';
import { getCurrentUser, logoutUser } from '../utils/api'; // Assumes apiRequest handles errors appropriately
import { showErrorToast } from '../utils/notifications'; // Import error toast
import { useRouter } from 'next/router';

// Define the shape of the context data
const AuthContext = createContext({
    user: null,
    setUser: (user) => {}, // Setter exposed - USE WITH EXTREME CAUTION
    isPgpAuthenticated: false,
    isLoading: true, // Indicates initial auth check loading state
    login: (userData, pgpVerified) => {},
    logout: async () => {},
    setPgpVerified: (isVerified) => {}, // Function to explicitly set PGP state
});

export const AuthProvider = ({ children }) => {
    const [user, setUser] = useState(null);
    const [isPgpAuthenticated, setIsPgpAuthenticated] = useState(false);
    const [isLoading, setIsLoading] = useState(true);
    const router = useRouter();

    // Check auth status on initial application load
    useEffect(() => {
        let isMounted = true; // Prevent state updates if component unmounts during async op

        const checkAuth = async () => {
            // Avoid check if already determined (e.g., navigated away quickly)
             if (!isMounted) return;

            setIsLoading(true);
            try {
                // Check if user is logged in via backend session cookie (assumed HttpOnly, Secure, SameSite)
                const currentUser = await getCurrentUser(); // Hits /api/store/users/me/

                // --- CRITICAL BACKEND DEPENDENCY ---
                // The '/users/me/' endpoint MUST reliably return a boolean flag indicating
                // if the CURRENT SESSION is PGP authenticated (2FA verified).
                // Adjust 'is_session_pgp_authenticated' to match the actual field name from your API.
                // Without this, the isPgpAuthenticated state will be INCORRECT on page load/refresh.
                const sessionIsPgpVerified = currentUser?.is_session_pgp_authenticated || false;

                 if (isMounted) {
                    setUser(currentUser);
                    setIsPgpAuthenticated(sessionIsPgpVerified);
                 }

            } catch (error) {
                 if (isMounted) {
                    // Handle errors from getCurrentUser
                    if (error.message === 'Unauthorized') {
                        // Expected if not logged in, clear state silently.
                    } else {
                        // Log unexpected errors and inform the user
                        console.error("Error during initial auth check:", error);
                        // Show toast for unexpected errors (e.g., network, server issue)
                        showErrorToast(`Failed to check login status: ${error.message}`);
                    }
                    setUser(null);
                    setIsPgpAuthenticated(false);
                 }
            } finally {
                 if (isMounted) {
                    setIsLoading(false);
                 }
            }
        };

        checkAuth();

        return () => {
             isMounted = false; // Cleanup function to prevent state updates on unmounted component
        };
        // Run only once on component mount
    }, []); // Empty dependency array ensures this runs only once on mount

    /**
     * Sets user state after successful login (including PGP verification step).
     * Relies on secure HttpOnly session cookie managed by the backend for persistence.
     * @param {object} userData - The user object received from the backend.
     * @param {boolean} [pgpVerified=true] - Whether the login process included successful PGP verification.
     */
    const login = useCallback((userData, pgpVerified = true) => {
        setUser(userData);
        setIsPgpAuthenticated(pgpVerified);
        // NOTE: PGP Status Synchronization Limitation:
        // The isPgpAuthenticated state reflects the status *at the time of login* or *initial load*.
        // If the backend PGP session status can expire independently (e.g., timeout),
        // this frontend state might become stale without a page refresh or explicit re-check.
        // Implementing real-time sync (e.g., periodic checks, WebSockets) adds complexity.
    }, []);

    /**
     * Logs the user out by calling the backend endpoint and clearing client-side state.
     */
    const logout = useCallback(async () => {
        try {
            await logoutUser(); // Call the backend logout endpoint
        } catch (error) {
            console.error("Logout API call failed (proceeding with client logout):", error);
            // Optionally show a generic error toast if API logout fails, but still log out locally.
             // showErrorToast("Could not properly end session on server, but logging out locally.");
        } finally {
            // ALWAYS clear client-side state and redirect.
            setUser(null);
            setIsPgpAuthenticated(false);
            // Redirect to login page after state is cleared.
            // Use replace to prevent user from navigating back to the logged-in state page
            router.replace('/login');
        }
    }, [router]);

    /**
     * Allows explicitly setting the PGP verification status.
     * CAUTION: Only use this if another action definitively changes the backend session's
     * PGP status and you need to reflect it immediately without a full user fetch.
     * Prefer deriving status from initial check or login whenever possible.
     * @param {boolean} isVerified - The new PGP verification status.
     */
    const setPgpVerified = useCallback((isVerified) => {
        setIsPgpAuthenticated(isVerified);
    }, []);


    // Memoize the context value to prevent unnecessary re-renders of consumers
    const contextValue = React.useMemo(() => ({
        user,
        // CAUTION: Exposing setUser allows direct state manipulation.
        // This can be useful but risks putting UI state out of sync with the backend session.
        // Prefer using dedicated functions like login/logout or API calls that refresh user data.
        setUser,
        isLoading,
        login,
        logout,
        isPgpAuthenticated,
        setPgpVerified
    }), [user, isLoading, login, logout, isPgpAuthenticated, setPgpVerified]); // Include setUser in dependency array

    return (
        <AuthContext.Provider value={contextValue}>
            {children}
        </AuthContext.Provider>
    );
};

// Custom hook to simplify consuming the AuthContext
export const useAuth = () => {
    const context = useContext(AuthContext);
    if (context === undefined) {
        throw new Error('useAuth must be used within an AuthProvider');
    }
    return context;
};
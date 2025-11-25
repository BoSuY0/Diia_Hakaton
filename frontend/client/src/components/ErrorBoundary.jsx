import React from 'react';

export class ErrorBoundary extends React.Component {
    constructor(props) {
        super(props);
        this.state = { hasError: false, error: null };
    }

    static getDerivedStateFromError(error) {
        return { hasError: true, error };
    }

    componentDidCatch(error, errorInfo) {
        console.error('ErrorBoundary caught an error:', error, errorInfo);
    }

    handleReset = () => {
        this.setState({ hasError: false, error: null });
        window.location.reload();
    };

    render() {
        if (this.state.hasError) {
            return (
                <div style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    minHeight: '100vh',
                    padding: 24,
                    textAlign: 'center',
                    background: '#F9FAFB'
                }}>
                    <div style={{
                        background: 'white',
                        borderRadius: 16,
                        padding: 32,
                        maxWidth: 400,
                        boxShadow: '0 4px 6px -1px rgba(0,0,0,0.1)'
                    }}>
                        <h2 style={{ color: '#DC2626', marginBottom: 16 }}>
                            😔 Щось пішло не так
                        </h2>
                        <p style={{ color: '#6B7280', marginBottom: 24 }}>
                            Виникла неочікувана помилка. Спробуйте оновити сторінку.
                        </p>
                        <button
                            onClick={this.handleReset}
                            style={{
                                background: '#3B82F6',
                                color: 'white',
                                border: 'none',
                                borderRadius: 12,
                                padding: '12px 24px',
                                fontSize: 16,
                                cursor: 'pointer'
                            }}
                        >
                            🔄 Оновити сторінку
                        </button>
                        {process.env.NODE_ENV === 'development' && this.state.error && (
                            <details style={{ marginTop: 24, textAlign: 'left' }}>
                                <summary style={{ cursor: 'pointer', color: '#9CA3AF' }}>
                                    Деталі помилки
                                </summary>
                                <pre style={{
                                    background: '#F3F4F6',
                                    padding: 12,
                                    borderRadius: 8,
                                    fontSize: 12,
                                    overflow: 'auto',
                                    marginTop: 8
                                }}>
                                    {this.state.error.toString()}
                                </pre>
                            </details>
                        )}
                    </div>
                </div>
            );
        }

        return this.props.children;
    }
}

package ch.omnilink.fhir.mdm.extension;

import jakarta.servlet.Filter;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.ServletRequest;
import jakarta.servlet.ServletResponse;
import jakarta.servlet.http.HttpServletRequest;
import java.io.IOException;
import java.sql.Connection;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.Objects;
import javax.sql.DataSource;

public final class ProjectionReadLockFilter implements Filter {
    private static final String ACQUIRE_READER_LOCK_SQL = "SELECT omni_projection_acquire_reader_lock()";

    private final DataSource dataSource;

    public ProjectionReadLockFilter(DataSource dataSource) {
        this.dataSource = Objects.requireNonNull(dataSource);
    }

    @Override
    public void doFilter(ServletRequest request, ServletResponse response, FilterChain chain)
            throws IOException, ServletException {
        if (!(request instanceof HttpServletRequest httpRequest) || !requiresReaderLock(httpRequest)) {
            chain.doFilter(request, response);
            return;
        }

        try (Connection connection = dataSource.getConnection()) {
            connection.setAutoCommit(false);
            if (!acquireReaderLock(connection)) {
                connection.rollback();
                chain.doFilter(request, response);
                return;
            }
            Throwable requestFailure = null;
            try {
                chain.doFilter(request, response);
            } catch (IOException | ServletException | RuntimeException | Error failure) {
                requestFailure = failure;
                throw failure;
            } finally {
                try {
                    connection.rollback();
                } catch (SQLException rollbackFailure) {
                    if (requestFailure != null) {
                        requestFailure.addSuppressed(rollbackFailure);
                    } else {
                        throw new ServletException("Cannot release Patient projection reader lock", rollbackFailure);
                    }
                }
            }
        } catch (SQLException failure) {
            throw new ServletException("Cannot hold Patient projection reader lock for the FHIR request", failure);
        }
    }

    private static boolean acquireReaderLock(Connection connection) throws SQLException {
        try (Statement statement = connection.createStatement()) {
            try (var protocol = statement.executeQuery(
                    "SELECT to_regprocedure('omni_projection_acquire_reader_lock()') IS NOT NULL")) {
                if (!protocol.next()) {
                    throw new SQLException("Patient projection reader protocol check returned no row");
                }
                if (!protocol.getBoolean(1)) {
                    return false;
                }
            }
            statement.execute("SET LOCAL application_name = 'omni-projection-reader-lock'");
            try (var rows = statement.executeQuery(ACQUIRE_READER_LOCK_SQL)) {
                if (!rows.next()) {
                    throw new SQLException("Patient projection reader lock returned no generation");
                }
            }
        }
        return true;
    }

    private static boolean requiresReaderLock(HttpServletRequest request) {
        String uri = request.getRequestURI();
        int fhirBase = uri.indexOf("/fhir");
        if (fhirBase < 0) {
            return false;
        }
        String path = uri.substring(fhirBase + "/fhir".length());
        if ("GET".equals(request.getMethod())) {
            return path.startsWith("/Patient")
                    || path.startsWith("/Binary")
                    || path.startsWith("/Group")
                    || path.equals("/_history")
                    || path.equals("/$export")
                    || path.equals("/$export-poll-status")
                    || path.startsWith("/$mdm-");
        }
        if (!"POST".equals(request.getMethod())) {
            return false;
        }
        return path.endsWith("/_search")
                || path.endsWith("/$export")
                || path.equals("/$export-poll-status")
                || path.startsWith("/$mdm-");
    }
}

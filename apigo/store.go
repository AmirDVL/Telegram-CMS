package main

import (
	"context"
	"errors"

	"github.com/jackc/pgx/v5"
)

// getAdminByID loads a non-disabled admin by id, returning (nil, nil) if absent.
func (a *App) getAdminByID(ctx context.Context, id int64) (*adminRow, error) {
	row := a.db.QueryRow(ctx,
		`SELECT `+adminCols+` FROM admins WHERE id=$1 AND disabled_at IS NULL`, id)
	admin, err := scanAdmin(row)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return admin, nil
}

// scoped reports whether a query should be tenant-scoped, mirroring
// shared.tenant.scope_query: only when multi-tenancy is on and a tenant is set.
func (a *App) scoped(tid *int64) bool {
	return a.cfg.MultiTenancy && tid != nil
}

// tenantOwned mirrors shared.tenant.get_scoped's ownership assertion: returns
// true if the row (with the given owner tenant_id) is visible to tid.
func (a *App) tenantOwned(tid *int64, owner *int64) bool {
	if !a.scoped(tid) {
		return true
	}
	return owner != nil && *owner == *tid
}

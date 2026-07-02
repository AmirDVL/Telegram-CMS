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
